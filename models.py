# 각 테이블 역할
# devices — AI 기기 정보
# campaigns — 광고 캠페인 정보
# device_campaigns — 기기와 캠페인 연결 (다대다)
# segment_logs — 배치 메타데이터
# events_raw — 원본 로그 (핵심 테이블)
# campaign_aggs — 캠페인 전체 기간 기본 집계
# campaign_advanced_aggs — 캠페인 전체 기간 고급 분석 집계
# dbscan_aggs — 골든존 DBSCAN 분석 결과
# [비활성화] daily_aggs / hourly_aggs — 실시간 ROI 통계 기능 추가로 대체 예정

from sqlalchemy import Column, String, Integer, Float, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, text, Enum, BigInteger, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from enums import DeviceStatus, CampaignStatus, UserRole

Base = declarative_base()


# 0-0. 이메일 인증 코드
class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    email      = Column(String(255), nullable=False, index=True)
    code       = Column(String(6),   nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used    = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# 0-1. 로그아웃된 토큰 블랙리스트
class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti        = Column(String(36), primary_key=True)
    revoked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


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

    events           = relationship("EventRaw", back_populates="device")
    device_campaigns = relationship("DeviceCampaign", back_populates="device", cascade="all, delete-orphan")
    segment_logs     = relationship("SegmentLog", back_populates="device")


# 2. 관심 구역 (ROI) — 비활성화
# class ROI(Base): ...


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

    # 타겟 인구통계 (타겟 오디언스 정합률 계산용, nullable — 설정 안 할 수도 있음)
    target_age_group = Column(String(20), nullable=True)   # 예: "20-29"
    target_gender    = Column(String(10), nullable=True)   # "male" / "female"

    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'RUNNING', 'PAUSED', 'ENDED')", name="chk_campaign_status"),
        CheckConstraint("end_date >= start_date", name="chk_campaign_dates"),
        CheckConstraint(
            "target_age_group IN ('10-19', '20-29', '30-39', '40-49', '50-59', '60+') OR target_age_group IS NULL",
            name="chk_campaign_target_age_group"
        ),
        CheckConstraint(
            "target_gender IN ('male', 'female') OR target_gender IS NULL",
            name="chk_campaign_target_gender"
        ),
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
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)

    track_id          = Column(Integer, nullable=False)
    exposure_start_ms = Column(Integer, nullable=False)
    exposure_end_ms   = Column(Integer, nullable=False)
    exposure_ms       = Column(Integer, nullable=False)

    # look_times: start_center, end_center 좌표 포함 (골든존 분석용)
    # [{"start_ms": int, "end_ms": int, "start_center": [x,y], "end_center": [x,y]}]
    look_times             = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    total_look_duration_ms = Column(Integer, nullable=False, default=0)

    # 첫 주목 반응 시간 계산용 — AI팀에서 나중에 제공 예정, nullable
    roi_entry_ms = Column(Integer, nullable=True)

    # 인구통계
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
    campaign = relationship("Campaign", back_populates="events")


# 4-1. DBSCAN 골든존 분석 결과 (캠페인 × 기기 단위, 1행 = 클러스터 1개)
class DbscanAgg(Base):
    __tablename__ = "dbscan_aggs"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    eps           = Column(Float,   nullable=False)
    min_samples   = Column(Integer, nullable=False)
    n_interp      = Column(Integer, nullable=False)

    point_count   = Column(Integer, nullable=False)
    event_count   = Column(Integer, nullable=False)
    noise_count   = Column(Integer, nullable=False)
    cluster_count = Column(Integer, nullable=False)

    cluster_label       = Column(Integer, nullable=False)
    cluster_point_count = Column(Integer, nullable=False)
    points              = Column(JSONB, nullable=True)

    device   = relationship("Device")
    campaign = relationship("Campaign")


# 공통 집계 컬럼 Mixin (CampaignAgg에서 사용)
class AggMixin:
    exposure_count          = Column(Integer, nullable=False, default=0)
    avg_dwell_time_ms       = Column(Float,   nullable=False, default=0.0)
    interested_count        = Column(Integer, nullable=False, default=0)
    attention_rate_tracks   = Column(Float,   nullable=False, default=0.0)
    total_attention_time_ms = Column(Float,   nullable=False, default=0.0)
    attention_rate_times    = Column(Float,   nullable=False, default=0.0)

    count_10s      = Column(Integer, nullable=False, default=0)
    count_20s      = Column(Integer, nullable=False, default=0)
    count_30s      = Column(Integer, nullable=False, default=0)
    count_40s      = Column(Integer, nullable=False, default=0)
    count_50s_plus = Column(Integer, nullable=False, default=0)
    count_60s_plus = Column(Integer, nullable=False, default=0)

    count_male   = Column(Integer, nullable=False, default=0)
    count_female = Column(Integer, nullable=False, default=0)

    # 고급 지표
    avg_revisit_count       = Column(Float,   nullable=False, default=0.0)
    avg_fixation_latency_ms = Column(Float,   nullable=True)
    viewability_score       = Column(Float,   nullable=False, default=0.0)
    avg_attention_time_ms   = Column(Float,   nullable=False, default=0.0)  # 추가
    peak_hour               = Column(Integer, nullable=True)
    target_match_rate       = Column(Float,   nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# 5. 시간 단위 통계 집계 — 비활성화 (실시간 ROI 통계 기능으로 대체 예정)
# class HourlyAgg(AggMixin, Base):
#     __tablename__ = "hourly_aggs"
#     id          = Column(BigInteger, primary_key=True, autoincrement=True)
#     hour        = Column(DateTime(timezone=True), nullable=False)
#     device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
#     campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
#     __table_args__ = (UniqueConstraint("hour", "device_id", "campaign_id", name="uq_hourly_agg"),)
#     device   = relationship("Device")
#     campaign = relationship("Campaign")


# 6. 일 단위 통계 집계 — 비활성화 (실시간 ROI 통계 기능으로 대체 예정)
# class DailyAgg(AggMixin, Base):
#     __tablename__ = "daily_aggs"
#     id          = Column(BigInteger, primary_key=True, autoincrement=True)
#     date        = Column(Date, nullable=False)
#     device_id   = Column(UUID(as_uuid=True), ForeignKey("devices.id",   ondelete="CASCADE"), nullable=False)
#     campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
#     __table_args__ = (UniqueConstraint("date", "device_id", "campaign_id", name="uq_daily_agg"),)
#     device   = relationship("Device")
#     campaign = relationship("Campaign")


# 7. 캠페인 전체 기간 기본 집계
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