# sqlalchemy
from sqlalchemy import Column, String, Integer, Float, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, text, Enum, BigInteger, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
# enum
from enums import DeviceStatus, CampaignStatus, UserRole
 
Base = declarative_base()
 
 
# 0. 유저 (로그인)
class User(Base):
    __tablename__ = "users"
 
    # 사용자 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # 이메일로 로그인 / unique=True로 중복 가입 방지
    # 회원가입을 하는 유저가 많아지면 제약조건에 index=True를 추가할 것
    email = Column(String(255), unique=True, nullable=False)
    # 비밀번호
    hashed_password = Column(String(255), nullable=False)
    # Admin / User
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    # 회원탈퇴 시 비활성화
    is_active = Column(Boolean, default=True)
    # 생성 시간
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # 업데이트 시간
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
 
 
# 1. 기기 (카메라/센서)
class Device(Base):
    __tablename__ = "devices"
 
    # 기기 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
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
 
 
"""
!!! 비활성화 !!!
!!! 비활성화 !!!
!!! 비활성화 !!!
 2. 관심 구역 (ROI)
class ROI(Base):
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
 
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_roi_device_name"),
    )
 
    device = relationship("Device", back_populates="rois")
    events = relationship("EventRaw", back_populates="roi")
"""
 
# 3. 광고 캠페인
class Campaign(Base):
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
 
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'RUNNING', 'PAUSED', 'ENDED')", name="chk_campaign_status"),
        CheckConstraint("end_date >= start_date", name="chk_campaign_dates"),
    )
 
    events = relationship("EventRaw", back_populates="campaign")
 
 
# 4. 실시간 수집 원본 로그 (track 단위 1행)
class EventRaw(Base):
    __tablename__ = "events_raw"
 
    # 로그 고유번호
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
 
    # 로그 수신 시간 (서버가 요청을 받은 시각 — 시간대 집계 기준점)
    # ts 제거: AI팀이 별도로 보내지 않으며, 서버 수신 시각으로 통일
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
 
    # 외래키
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="RESTRICT"), nullable=False)
    roi_id      = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="RESTRICT"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)
 
    # AI팀 track 식별자 (배치 내 정수 ID)
    track_id = Column(Integer, nullable=False)
 
    # 노출 정보 (ms 단위)
    exposure_start_ms = Column(Integer, nullable=False)
    exposure_end_ms   = Column(Integer, nullable=False)
    exposure_dwell_ms = Column(Integer, nullable=False)
 
    # 시선 구간 목록 (JSONB 유지 — 원본 보존 목적)
    look_times = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
 
    # 총 시선 시간 (ms 단위)
    total_look_duration_ms = Column(Integer, nullable=False, default=0)
 
    # 인구통계 (nullable — AI가 분석 못할 수도 있음)
    age_group = Column(String(20), nullable=True)
    CheckConstraint("age_group IN (('10s', '20s','30s','40s', '50s' '60u'))", name="chk_age_group")
    gender    = Column(String(10), nullable=True) 
    CheckConstraint("gender IN ('male', 'female')", name="chk_gender")

 
    device   = relationship("Device",   back_populates="events")
    roi      = relationship("ROI",      back_populates="events")
    campaign = relationship("Campaign", back_populates="events")
 
 
# 5. 시간 단위 통계 집계 (Hourly Aggregation)
# 분석 목적: 시간대별 유동인구 및 광고 몰입도 추이 파악
class HourlyAgg(Base):
    __tablename__ = "hourly_aggs"
 
    # 집계 데이터 고유 번호 (공간 복잡도를 줄이기 위해 BigInt 사용)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
 
    # 집계 대상 시간 (예: 2026-03-10 14:00:00+09:00)
    hour = Column(DateTime(timezone=True), nullable=False)
 
    # 외래키
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    roi_id      = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
 
    # 노출 / 관심 인구
    exposure_count   = Column(Integer, nullable=False, default=0)   # 총 노출 인구
    interested_count = Column(Integer, nullable=False, default=0)   # 관심 인구 (look_times 있는 사람)
    attention_rate   = Column(Float,   nullable=False, default=0.0) # 관심도 = interested_count / exposure_count
 
    # 나이대별 인원 (확정 5개 구간)
    count_10s      = Column(Integer, nullable=False, default=0)  # 10대
    count_20s      = Column(Integer, nullable=False, default=0)  # 20대
    count_30s      = Column(Integer, nullable=False, default=0)  # 30대
    count_40s      = Column(Integer, nullable=False, default=0)  # 40대
    count_50s_plus = Column(Integer, nullable=False, default=0)  # 50대 이상
 
    # 성별 인원
    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)
 
    # 배치 작업 추적용
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
 
    device   = relationship("Device")
    roi      = relationship("ROI")
    campaign = relationship("Campaign")

    # 제약조건 : 날짜, 기기 고유번호, roi 고유번호, 광고 고유번호를 유니크로 함
    __table_args__ = (
    UniqueConstraint("hour", "device_id", "roi_id", "campaign_id", name="uq_hourly_agg"),
    )


 
 
# 6. 일 단위 통계 집계 (Daily Aggregation)
# 분석 목적: 일자별 광고 성과 리포트 및 장기적인 캠페인 효율 측정
class DailyAgg(Base):
    __tablename__ = "daily_aggs"
 
    # 집계 데이터 고유 번호
    id = Column(BigInteger, primary_key=True, autoincrement=True)
 
    # 집계 대상 날짜 (예: 2026-03-10)
    date = Column(Date, nullable=False)
 
    # 외래키
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    roi_id      = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
 
    # 노출 / 관심 인구
    exposure_count   = Column(Integer, nullable=False, default=0)   # 총 노출 인구
    interested_count = Column(Integer, nullable=False, default=0)   # 관심 인구 (look_times 있는 사람)
    attention_rate   = Column(Float,   nullable=False, default=0.0) # 관심도 = interested_count / exposure_count
 
    # 나이대별 인원 (확정 5개 구간)
    count_10s      = Column(Integer, nullable=False, default=0)  # 10대
    count_20s      = Column(Integer, nullable=False, default=0)  # 20대
    count_30s      = Column(Integer, nullable=False, default=0)  # 30대
    count_40s      = Column(Integer, nullable=False, default=0)  # 40대
    count_50s_plus = Column(Integer, nullable=False, default=0)  # 50대 이상
 
    # 성별 인원
    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)
 
    # 배치 작업 추적용
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
 
    device   = relationship("Device")
    roi      = relationship("ROI")
    campaign = relationship("Campaign")

    # 제약조건 : 날짜, 기기 고유번호, roi 고유번호, 광고 고유번호를 유니크로 함
    __table_args__ = (
    UniqueConstraint("date", "device_id", "roi_id", "campaign_id", name="uq_daily_agg"),
    )