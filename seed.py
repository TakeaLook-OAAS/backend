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
USER_EMAIL     = "usertakealook@naver.com"
USER_PASSWORD  = "takealook"
DEVICE_ADDRESS = "서울특별시 종로구 홍지문2길 20"
DEVICE_LAT     = 37.6026
DEVICE_LNG     = 126.9553


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 이미 존재하면 스킵
        if db.query(User).filter_by(id=ADMIN_ID).first():
            print("이미 시드 데이터가 존재합니다. 스킵합니다.")
            return

        # 1. 관리자
        admin = User(
            id=ADMIN_ID,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)

        # 1-2. 일반 사용자
        user = User(
            id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001"),
            email=USER_EMAIL,
            hashed_password=hash_password(USER_PASSWORD),
            role=UserRole.USER,
            is_active=True,
        )
        db.add(user)

        # 2. 디바이스
        device = Device(
            id=DEVICE_ID,
            name="상명대학교 공학관 G203",
            status=DeviceStatus.ENABLE,
            timezone="Asia/Seoul",
            address=DEVICE_ADDRESS,
            latitude=DEVICE_LAT,
            longitude=DEVICE_LNG,
        )
        db.add(device)

        # 3. 캠페인
        campaign = Campaign(
            id=CAMPAIGN_ID,
            user_id=ADMIN_ID,
            name="졸업전시",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=CampaignStatus.RUNNING,
            addresses=[{
                "addr": DEVICE_ADDRESS,
                "label": "상명대학교 공학관 G203",
                "device_id": str(DEVICE_ID),
            }],
        )
        db.add(campaign)

        db.flush()  # FK 참조 전 먼저 반영

        # 4. 디바이스-캠페인 연결 (cycle_index=0)
        dc = DeviceCampaign(
            device_id=DEVICE_ID,
            campaign_id=CAMPAIGN_ID,
            cycle_index=0,
            ad_duration_sec=15,   # 내 광고 15초
            cycle_total_sec=60,   # 사이클 총 60초 → SOV = 0.25
        )
        db.add(dc)

        db.commit()
        print("시드 완료:")
        print(f"  admin : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"  user  : {USER_EMAIL} / {USER_PASSWORD}")
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
