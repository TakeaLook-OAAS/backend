# 각 테이블 역할
# devices — AI 기기 정보
# 기기 이름, 상태(ENABLE/DISABLE), 타임존
# campaigns — 광고 캠페인 정보
# 광고명, 시작일, 종료일, 상태(DRAFT/RUNNING/PAUSED/ENDED)
# device_campaigns — 기기와 캠페인 연결 (다대다)
# device_id + campaign_id + cycle_index
# → "이 기기에서 몇 번째 광고가 어떤 캠페인인지"
# 예시:
# 기기A + cycle_index=0 → 삼성 광고
# 기기A + cycle_index=1 → 나이키 광고
# 기기A + cycle_index=2 → 애플 광고
# segment_logs — 배치 메타데이터
# 배치가 언제 왔는지, roi_polygon이 뭔지
# → 나중에 골든존 분석할 때 사용
# events_raw — 원본 로그 (핵심 테이블)
# track 1개 = 1행
# 사람 1명의 노출 정보, 시선 정보, 나이대, 성별
# daily_aggs / hourly_aggs / campaign_aggs — 집계 결과
# events_raw를 날짜/시간/캠페인 단위로 집계한 결과
# 프론트가 이 테이블에서 데이터를 가져감
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
class DeviceCampaign(Base):
    __tablename__ = "device_campaigns"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    cycle_index = Column(Integer, nullable=False)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("device_id", "cycle_index", name="uq_device_cycle"),
        UniqueConstraint("device_id", "campaign_id", name="uq_device_campaign"),
    )

    device   = relationship("Device",   back_populates="device_campaigns")
    campaign = relationship("Campaign", back_populates="device_campaigns")


# 3-2. 배치 세그먼트 로그
class SegmentLog(Base):
    __tablename__ = "segment_logs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    ts          = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)
    index       = Column(Integer, nullable=False)
    cycle_index = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    roi_polygon = Column(JSONB, nullable=True)

    device = relationship("Device", back_populates="segment_logs")


# 4. 실시간 수집 원본 로그 (track 단위 1행)
class EventRaw(Base):
    __tablename__ = "events_raw"

    id          = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    ts          = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="RESTRICT"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="RESTRICT"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)

    track_id          = Column(Integer, nullable=False)
    exposure_start_ms = Column(Integer, nullable=False)
    exposure_end_ms   = Column(Integer, nullable=False)
    exposure_ms       = Column(Integer, nullable=False)  # end_ms - start_ms

    # look_times: start_center, end_center 좌표 포함 (골든존 분석용)
    # [{"start_ms": int, "end_ms": int, "start_center": [x,y], "end_center": [x,y]}]
    look_times             = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    total_look_duration_ms = Column(Integer, nullable=False, default=0)

    # 인구통계 (nullable — AI가 분석 못할 수도 있음, "unknown"은 None으로 변환)
    age_group = Column(String(20), nullable=True)
    gender    = Column(String(10), nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "track_id", "ts", name="uq_event_raw_track"),
        CheckConstraint(
            "age_group IN ('10-19', '20-29', '30-39', '40-49', '50-59', '60+') OR age_group IS NULL",
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


# 공통 집계 컬럼 Mixin
# HourlyAgg, DailyAgg, CampaignAgg가 동일한 집계 컬럼을 공유
class AggMixin:
    # 노출 인구
    exposure_count        = Column(Integer, nullable=False, default=0)   # 전체 Track 수

    # 체류 시간
    avg_dwell_time_ms     = Column(Float,   nullable=False, default=0.0) # 총 체류시간 / 전체 Track 수

    # 관심도 지표
    interested_count      = Column(Integer, nullable=False, default=0)   # look_times 있는 Track 수
    attention_rate_tracks = Column(Float,   nullable=False, default=0.0) # interested_count / exposure_count
    total_attention_time_ms = Column(Float, nullable=False, default=0.0) # total_look_duration_ms 합계
    attention_rate_times  = Column(Float,   nullable=False, default=0.0) # total_attention_time_ms / sum(exposure_ms)

    # 나이대별 인원
    count_10s      = Column(Integer, nullable=False, default=0)  # 10-19
    count_20s      = Column(Integer, nullable=False, default=0)  # 20-29
    count_30s      = Column(Integer, nullable=False, default=0)  # 30-39
    count_40s      = Column(Integer, nullable=False, default=0)  # 40-49
    count_50s_plus = Column(Integer, nullable=False, default=0)  # 50-59
    count_60s_plus = Column(Integer, nullable=False, default=0)  # 60+

    # 성별 인원
    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# 5. 시간 단위 통계 집계 (Hourly Aggregation)
class HourlyAgg(AggMixin, Base):
    __tablename__ = "hourly_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    hour        = Column(DateTime(timezone=True), nullable=False)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("hour", "device_id", "campaign_id", name="uq_hourly_agg"),
    )

    device   = relationship("Device")
    # roi   = relationship("ROI")  # ROI 비활성화
    campaign = relationship("Campaign")


# 6. 일 단위 통계 집계 (Daily Aggregation)
class DailyAgg(AggMixin, Base):
    __tablename__ = "daily_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    date        = Column(Date, nullable=False)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    # roi_id   = Column(UUID(as_uuid=True), ForeignKey("rois.id",      ondelete="CASCADE"), nullable=False)  # ROI 비활성화
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "device_id", "campaign_id", name="uq_daily_agg"),
    )

    device   = relationship("Device")
    # roi   = relationship("ROI")  # ROI 비활성화
    campaign = relationship("Campaign")


# 7. 캠페인 전체 기간 집계 (Campaign Aggregation)
class CampaignAgg(AggMixin, Base):
    __tablename__ = "campaign_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("device_id", "campaign_id", name="uq_campaign_agg"),
    )

    device   = relationship("Device")
    campaign = relationship("Campaign")