#sqlalchemy
from sqlalchemy import Column, String, Integer, Float, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, text, Enum, BigInteger, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
#enum
from enums import DeviceStatus, CampaignStatus, UserRole

Base = declarative_base()

# 0. 유저 (로그인)
class User(Base):
    __tablename__ = "users"
    # 사용자 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # 이메일로 로그인 / unique=True로 중복 가입 방지 / 회원가입을 하는 유저가 많아지면 제약조건에 index=True를 추가할 것
    email = Column(String(255), unique=True,  nullable=False)
    # 비밀번호
    hashed_password = Column(String(255), nullable=False)
    # Admin / User
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    # 회원탈퇴 시 비활성화
    is_active = Column(Boolean, default=True)
    # 생성 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # 업데이트 시간
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now)

# 1. 기기 (카메라/센서)
class Device(Base):
    # 테이블 이름
    __tablename__ = "devices"

    # 기기 고유번호
    id = Column(UUID(as_uuid = True), primary_key=True, server_default=text("gen_random_uuid()"))
    # 기기 이름
    name = Column(String(20), nullable=False, unique=True)
    # 기기 상태
    status = Column(Enum(DeviceStatus), nullable=False, default=DeviceStatus.ENABLE)
    # 기기가 설치된 곳의 시간 / 기본값으로 Asia/Seoul
    timezone = Column(String(32), nullable=False)
    # 생성 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # 관계 설정 (역참조)
    rois = relationship("ROI", back_populates="device", cascade="all, delete-orphan")
    events = relationship("EventRaw", back_populates="device")


# 2. 관심 구역 (ROI)
class ROI(Base):
    # 테이블 이름
    __tablename__ = "rois"

    # roi 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # 이 roi를 촬영하는 기기의 id
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    # roi 이름
    name = Column(String(50), nullable=False)
    # roi의 좌표 데이터를 담을 JSONB
    polygon = Column(JSONB, nullable=False)
    # 생성 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # UNIQUE 제약조건 (같은 기기 내에서는 ROI 이름이 중복될 수 없음)
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_roi_device_name"),
    )

    # roi.device.---
    device = relationship("Device", back_populates="rois")
    # roi.events.---
    events = relationship("EventRaw", back_populates="roi")


# 3. 광고 캠페인
class Campaign(Base):
    # 테이블 이름
    __tablename__ = "campaigns"

    # 광고 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # 광고명
    name = Column(String(100), nullable=False)
    # 광고 시작일
    start_date = Column(Date, nullable=False)
    # 광고 종료일
    end_date = Column(Date, nullable=False)
    # 광고 상태
    status = Column(Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT)

    # 생성 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # 업데이트 시간
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # DB 레벨의 CHECK 제약조건 : status
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'RUNNING', 'PAUSED', 'ENDED')", name="chk_campaign_status"),
        CheckConstraint("end_date >= start_date", name="chk_campaign_dates"),
    )

    # campaign.events.---
    events = relationship("EventRaw", back_populates="campaign")


# 4. 실시간 수집 원본 로그
class EventRaw(Base):
    # 테이블 이름
    __tablename__ = "events_raw"

    # 로그 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    # ai에서 event_id를 만들지 않는다면 사용
    # event_id = Column(UUID(as_uuid=True), nullable=False, unique=True)

    # 로그 발생 시간
    ts = Column(DateTime(timezone=True), nullable=False)
    # 로그 수신 시간
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # 기기 고유번호
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    # roi 고유번호
    roi_id = Column(UUID(as_uuid=True), ForeignKey("rois.id", ondelete="RESTRICT"), nullable=False)
    # 광고 고유번호
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)
    # 로그 타입
    event_type = Column(String(24), nullable=False)
    # 수치
    value = Column(Float, nullable=False)
    # JSONB
    meta_data = Column("meta", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 음수값 거부
    __table_args__ = (
        CheckConstraint("value >= 0", name="chk_event_value"),
    )
    
    device = relationship("Device", back_populates="events")
    roi = relationship("ROI", back_populates="events")
    campaign = relationship("Campaign", back_populates="events")


# 5. 시간 단위 통계 집계 (Hourly Aggregation)
# 분석 목적: 시간대별 유동인구 및 광고 몰입도 추이 파악 (예: 퇴근 시간대 집중 분석)
class HourlyAgg(Base):
    __tablename__ = "hourly_aggs"

    # 집계 데이터 고유 번호 (공간 복잡도를 줄이기 위해 BigInt 사용)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # 집계 대상 시간 (예: 2026-03-10 14:00:00)
    hour = Column(DateTime(timezone=True), nullable=False)
    
    # 관계형 키: 어떤 기기의 어느 구역에서 발생한 통계인지 연결
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    roi_id = Column(UUID(as_uuid=True), ForeignKey("rois.id", ondelete="CASCADE"), nullable=False)
    
    # 관계형 키: 해당 시간에 어떤 광고 캠페인이 송출 중이었는지 연결
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    # --- 핵심 통계 지표 ---
    # 해당 시간 동안 감지된 총 이벤트(로그) 횟수
    event_count = Column(Integer, nullable=False, default=0)
    
    # 해당 시간 동안의 총 체류 시간 합계 (초 단위)
    total_value = Column(Float, nullable=False, default=0.0)
    
    # 해당 시간 동안의 평균 몰입도 또는 값 (total_value / event_count)
    avg_value = Column(Float, nullable=False, default=0.0)

    # 데이터 생성 및 최종 업데이트 시간 (배치 작업 추적용)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # 관계 설정
    device = relationship("Device")
    roi = relationship("ROI")
    campaign = relationship("Campaign")


# 6. 일 단위 통계 집계 (Daily Aggregation)
# 분석 목적: 일자별 광고 성과 리포트 및 장기적인 캠페인 효율 측정
class DailyAgg(Base):
    __tablename__ = "daily_aggs"

    # 집계 데이터 고유 번호
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # 집계 대상 날짜 (예: 2026-03-10)
    date = Column(Date, nullable=False)
    
    # 관계형 키 연결
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    roi_id = Column(UUID(as_uuid=True), ForeignKey("rois.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    # 하루 동안의 총 시청/이벤트 횟수 (광고주에게 가장 중요한 지표 중 하나)
    event_count = Column(Integer, nullable=False, default=0)
    
    # 하루 동안 누적된 총 체류 시간 합계
    total_value = Column(Float, nullable=False, default=0.0)
    
    # 하루 평균 수치
    avg_value = Column(Float, nullable=False, default=0.0)

    # 데이터 생성 및 최종 업데이트 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # 관계 설정
    device = relationship("Device")
    roi = relationship("ROI")
    campaign = relationship("Campaign")