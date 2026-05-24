"""
초기 데이터 시드 스크립트
- 관리자 유저, 디바이스, 캠페인, device_campaigns 연결을 고정 UUID로 생성
- down -v 후 재빌드해도 동일한 ID 유지
"""
import uuid
from datetime import date
from database.database import SessionLocal, engine
from database.models import Base, User, Device, Campaign, DeviceCampaign
from database.enums import UserRole, DeviceStatus, CampaignStatus
from core.security import hash_password

# ── 고정 ID (재빌드해도 변하지 않음) ─────────────────────────────────────────
DEVICE_ID   = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
CAMPAIGN_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
ADMIN_ID    = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

# ── 시드 데이터 ───────────────────────────────────────────────────────────────
ADMIN_EMAIL    = "teamtakealook@naver.com"
ADMIN_PASSWORD = "takealook"


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 이미 존재하면 스킵
        if db.query(User).filter_by(id=ADMIN_ID).first():
            print("이미 시드 데이터가 존재합니다. 스킵합니다.")
            return

        # 1. 관리자 유저
        admin = User(
            id=ADMIN_ID,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)

        # 2. 디바이스
        device = Device(
            id=DEVICE_ID,
            name="device-001",
            status=DeviceStatus.ENABLE,
            timezone="Asia/Seoul",
        )
        db.add(device)

        # 3. 캠페인
        campaign = Campaign(
            id=CAMPAIGN_ID,
            user_id=ADMIN_ID,
            name="테스트 캠페인",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=CampaignStatus.RUNNING,
        )
        db.add(campaign)

        db.flush()  # FK 참조 전 먼저 반영

        # 4. 디바이스-캠페인 연결 (cycle_index=0)
        dc = DeviceCampaign(
            device_id=DEVICE_ID,
            campaign_id=CAMPAIGN_ID,
            cycle_index=0,
        )
        db.add(dc)

        db.commit()
        print("시드 완료:")
        print(f"  admin : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"  device_id   : {DEVICE_ID}")
        print(f"  campaign_id : {CAMPAIGN_ID}")
        print(f"  cycle_index : 0 → campaign 연결됨")

    except Exception as e:
        db.rollback()
        print(f"시드 실패: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
