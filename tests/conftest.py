"""
테스트 시작
    ↓
테스트용 DB(test_oaas) 생성
    ↓
테이블 생성
    ↓
테스트 데이터 삽입 (device, campaign, device_campaigns)
    ↓
테스트 실행
    ↓
테이블 TRUNCATE (다음 테스트를 위해 초기화)
    ↓
테스트 종료 후 테이블 DROP

공용 pytest 픽스처 모음

테스트용 PostgreSQL DB: test_oaas
  - docker-compose의 같은 컨테이너를 사용하되, 별도 DB에서 격리
  - 테스트 세션 시작 시 테이블 생성, 종료 시 DROP
  - 각 테스트 함수 종료 후 모든 테이블 TRUNCATE → 독립적인 테스트 보장
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import pytest
from datetime import date
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

from models import Base, Device, Campaign, DeviceCampaign
from enums import DeviceStatus, CampaignStatus

ADMIN_URL = os.getenv("TEST_ADMIN_DB_URL")
TEST_DB_URL = os.getenv("TEST_DB_URL")

# DB 접속 정보는 .env에서 로드
# ── 세션 범위: 테스트 DB 생성 + 테이블 생성 ──────────────────────────────────

@pytest.fixture(scope="session")
def engine():
    """테스트 DB(test_oaas)를 생성하고 테이블을 만드는 세션 범위 픽스처."""
    admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'test_oaas'")
        ).fetchone()
        if not exists:
            conn.execute(text("CREATE DATABASE test_oaas"))
    admin_engine.dispose()

    test_engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    yield test_engine

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


# ── 함수 범위: 각 테스트 후 테이블 초기화 ────────────────────────────────────

@pytest.fixture(scope="function")
def db(engine) -> Session:
    """
    테스트용 DB 세션.
    테스트 함수가 끝나면 모든 테이블을 TRUNCATE하여 상태 초기화.
    """
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionFactory()
    yield session
    session.close()

    with engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE TABLE "
            "dbscan_aggs, campaign_aggs, hourly_aggs, daily_aggs, events_raw, segment_logs, "
            "device_campaigns, campaigns, devices, users "
            "RESTART IDENTITY CASCADE"
        ))
        conn.commit()


# ── 공용 시드 픽스처 ──────────────────────────────────────────────────────────

@pytest.fixture
def seed(db) -> dict:
    """
    테스트에 필요한 기본 데이터를 삽입하고 ID를 반환.

    세그먼트 파일의 cycle_index가 0, 1, 2 세 가지이므로
    campaign 3개와 device_campaigns 3개를 등록합니다.

    반환 딕셔너리:
        device_id    : UUID — ENABLE 상태의 기기
        campaign_ids : dict — {cycle_index: campaign_id}
    """
    device_id = uuid.uuid4()

    db.add(Device(
        id       = device_id,
        name     = "test-device-01",
        status   = DeviceStatus.ENABLE,
        timezone = "Asia/Seoul",
    ))

    # cycle_index 0, 1, 2에 해당하는 캠페인 3개 등록
    campaign_ids = {}
    for cycle_index in range(3):
        campaign_id = uuid.uuid4()
        db.add(Campaign(
            id         = campaign_id,
            name       = f"테스트 캠페인 {cycle_index}",
            start_date = date(2026, 1, 1),
            end_date   = date(2026, 12, 31),
            status     = CampaignStatus.RUNNING,
        ))
        db.add(DeviceCampaign(
            device_id   = device_id,
            campaign_id = campaign_id,
            cycle_index = cycle_index,
        ))
        campaign_ids[cycle_index] = campaign_id

    db.commit()

    return {
        "device_id":    device_id,
        "campaign_ids": campaign_ids,  # {0: uuid, 1: uuid, 2: uuid}
    }


# ── FastAPI 테스트 클라이언트 ─────────────────────────────────────────────────

@pytest.fixture
def client(db) -> TestClient:
    """
    get_db 의존성을 테스트 세션으로 교체한 FastAPI TestClient.
    """
    from main import app
    from database import get_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()