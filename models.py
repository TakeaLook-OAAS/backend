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

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    email           = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# 1. 기기 (카메라/센서)
class Device(Base):
    __tablename__ = "devices"

    id         = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name       = Column(String(20), nullable=False, unique=True)
    status     = Column(Enum(DeviceStatus), nullable=False, default=DeviceStatus.ENABLE)
    timezone   = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # rois             = relationship("ROI", back_populates="device", cascade="all, delete-orphan")  # ROI 비활성화
    events           = relationship("EventRaw", back_populates="device")
    device_campaigns = relationship("DeviceCampaign", back_populates="device", cascade="all, delete-orphan")
    segment_logs     = relationship("SegmentLog", back_populates="device")


# 2. 관심 구역 (ROI) — 비활성화
# class ROI(Base):
#     __tablename__ = "rois"
#     id         = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
#     device_id  = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
#     name       = Column(String(50), nullable=False)
#     polygon    = Column(JSONB, nullable=False)
#     created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
#     __table_args__ = (UniqueConstraint("device_id", "name", name="uq_roi_device_name"),)
#     device = relationship("Device", back_populates="rois")
#     events = relationship("EventRaw", back_populates="roi")


# 3. 광고 캠페인
class Campaign(Base):
    __tablename__ = "campaigns"

    id         = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name       = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date   = Column(Date, nullable=False)
    status     = Column(Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'RUNNING', 'PAUSED', 'ENDED')", name="chk_campaign_status"),
        CheckConstraint("end_date >= start_date", name="chk_campaign_dates"),
    )

    events           = relationship("EventRaw", back_populates="campaign")
    device_campaigns = relationship("DeviceCampaign", back_populates="campaign", cascade="all, delete-orphan")


# 3-1. 기기-캠페인 연결 (다대다 중간 테이블)
# AI팀이 device_id + cycle_index를 보내면 서버가 campaign_id를 찾아주는 구조
class DeviceCampaign(Base):
    __tablename__ = "device_campaigns"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    # 이 기기에서 몇 번째 광고인지 (AI팀이 segment.cycle_index로 보내주는 값)
    cycle_index = Column(Integer, nullable=False)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("device_id", "cycle_index", name="uq_device_cycle"),
        UniqueConstraint("device_id", "campaign_id", name="uq_device_campaign"),
    )

    device   = relationship("Device",   back_populates="device_campaigns")
    campaign = relationship("Campaign", back_populates="device_campaigns")


# 3-2. 배치 세그먼트 로그
# AI팀이 보내는 배치 단위 메타데이터를 저장합니다.
# roi_polygon을 track마다 중복 저장하지 않고 배치 단위(1행)로 저장합니다.
# 나중에 ROI 분석 (골든 존 탐색) 시 활용합니다.
class SegmentLog(Base):
    __tablename__ = "segment_logs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)

    # 배치 기준 시각 (segment.timestamp) — events_raw.ts와 동일한 값
    ts          = Column(DateTime(timezone=True), nullable=False)
    # 서버 수신 시각
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # 외래키
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)

    # 배치 메타데이터
    index       = Column(Integer, nullable=False)   # 배치 인덱스
    cycle_index = Column(Integer, nullable=False)   # 몇 번째 광고인지
    duration_ms = Column(Integer, nullable=False)   # 배치 지속 시간 (ms)

    # ROI 폴리곤 (화면 전체 좌표 4점)
    # 예: [[0,0],[1920,0],[1920,1080],[0,1080]]
    # 나중에 ROI를 줄여가며 관심도 증가율이 가장 높은 골든 존을 찾을 때 사용
    roi_polygon = Column(JSONB, nullable=True)

    device   = relationship("Device", back_populates="segment_logs")


# 4. 실시간 수집 원본 로그 (track 단위 1행)
class EventRaw(Base):
    __tablename__ = "events_raw"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    # AI팀이 찍은 배치 기준 시각 (segment.timestamp) — 집계 기준
    ts          = Column(DateTime(timezone=True), nullable=False)
    # 서버 수신 시각 — 배치 지연 모니터링용 (ts와 차이가 배치 주기보다 크면 경고)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # 외래키
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="RESTRICT"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="RESTRICT"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)

    # AI팀 track 식별자 (배치 내 정수 ID)
    track_id = Column(Integer, nullable=False)

    # 노출 정보 (ms 단위)
    exposure_start_ms = Column(Integer, nullable=False)
    exposure_end_ms   = Column(Integer, nullable=False)
    exposure_ms       = Column(Integer, nullable=False)  # end_ms - start_ms

    # 시선 구간 목록 (JSONB 유지 — 원본 보존 목적)
    # duration_ms는 AI팀이 보내지 않으며 백엔드에서 end_ms - start_ms로 계산
    look_times = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    # 총 시선 시간 (ms 단위)
    total_look_duration_ms = Column(Integer, nullable=False, default=0)

    # 인구통계 (nullable — AI가 분석 못할 수도 있음)
    # "unknown"은 수신 시 None으로 변환하여 저장
    age_group = Column(String(20), nullable=True)
    gender    = Column(String(10), nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "track_id", "ts", name="uq_event_raw_track"),
        CheckConstraint(
            "age_group IN ('10-19', '20-29', '30-39', '40-49', '50-59') OR age_group IS NULL",
            name="chk_age_group"
        ),
        CheckConstraint(
            "gender IN ('male', 'female') OR gender IS NULL",
            name="chk_gender"
        ),
    )

    device   = relationship("Device",   back_populates="events")
    # roi   = relationship("ROI",      back_populates="events")  # ROI 비활성화
    campaign = relationship("Campaign", back_populates="events")


# 5. 시간 단위 통계 집계 (Hourly Aggregation)
class HourlyAgg(Base):
    __tablename__ = "hourly_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    hour        = Column(DateTime(timezone=True), nullable=False)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    exposure_count      = Column(Integer, nullable=False, default=0)
    interested_count    = Column(Integer, nullable=False, default=0)
    attention_rate      = Column(Float,   nullable=False, default=0.0)
    avg_viewing_time_ms = Column(Float,   nullable=False, default=0.0)

    count_10s      = Column(Integer, nullable=False, default=0)
    count_20s      = Column(Integer, nullable=False, default=0)
    count_30s      = Column(Integer, nullable=False, default=0)
    count_40s      = Column(Integer, nullable=False, default=0)
    count_50s_plus = Column(Integer, nullable=False, default=0)

    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("hour", "device_id", "campaign_id", name="uq_hourly_agg"),
    )

    device   = relationship("Device")
    # roi   = relationship("ROI")  # ROI 비활성화
    campaign = relationship("Campaign")


# 6. 일 단위 통계 집계 (Daily Aggregation)
class DailyAgg(Base):
    __tablename__ = "daily_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    date        = Column(Date, nullable=False)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    exposure_count      = Column(Integer, nullable=False, default=0)
    interested_count    = Column(Integer, nullable=False, default=0)
    attention_rate      = Column(Float,   nullable=False, default=0.0)
    avg_viewing_time_ms = Column(Float,   nullable=False, default=0.0)

    count_10s      = Column(Integer, nullable=False, default=0)
    count_20s      = Column(Integer, nullable=False, default=0)
    count_30s      = Column(Integer, nullable=False, default=0)
    count_40s      = Column(Integer, nullable=False, default=0)
    count_50s_plus = Column(Integer, nullable=False, default=0)

    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("date", "device_id", "campaign_id", name="uq_daily_agg"),
    )

    device   = relationship("Device")
    # roi   = relationship("ROI")  # ROI 비활성화
    campaign = relationship("Campaign")