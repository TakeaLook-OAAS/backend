from pydantic import BaseModel, Field, ConfigDict, computed_field
from datetime import datetime, date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, computed_field, field_validator


# ── AI팀 JSON 내부 구조 ──────────────────────────────────────────────────────

class SegmentData(BaseModel):
    """배치 메타데이터"""
    device_id:   str
    index:       int
    cycle_index: int
    timestamp:   datetime
    duration_ms: int
    roi_polygon: Optional[List[List[int]]] = None


class ExposureData(BaseModel):
    start_ms: int
    end_ms:   int

    @computed_field
    @property
    def exposure_ms(self) -> int:
        """백엔드에서 계산 (end_ms - start_ms)"""
        return self.end_ms - self.start_ms


class LookTime(BaseModel):
    start_ms:     int
    end_ms:       int
    in_roi:       Optional[bool]         = None
    start_center: Optional[List[int]]    = None  # [x, y] — 골든존 분석용
    end_center:   Optional[List[int]]    = None  # [x, y] — 골든존 분석용

    @computed_field
    @property
    def duration_ms(self) -> int:
        """백엔드에서 계산 (end_ms - start_ms)"""
        return self.end_ms - self.start_ms


class TrackData(BaseModel):
    track_id:               int
    exposure:               ExposureData
    look_times:             List[LookTime]
    total_look_duration_ms: int
    age_group:              Optional[str] = None
    gender:                 Optional[str] = None


# ── 수신용 (요청 바디) ────────────────────────────────────────────────────────

class EventBatchCreate(BaseModel):
    """AI팀에서 한 번에 보내는 배치 단위 요청"""
    segment: SegmentData
    tracks:  List[TrackData] = Field(..., description="track 목록")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "segment": {
                    "device_id":   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                    "index":       0,
                    "cycle_index": 0,
                    "timestamp":   "2026-04-03T13:48:11.486512+00:00",
                    "duration_ms": 20000,
                    "roi_polygon": [[0,0],[1920,0],[1920,1080],[0,1080]]
                },
                "tracks": [
                    {
                        "track_id": 1,
                        "exposure": {"start_ms": 0, "end_ms": 5605},
                        "look_times": [
                            {
                                "start_ms": 3970,
                                "end_ms": 4504,
                                "start_center": [1195, 321],
                                "end_center": [1210, 274]
                            }
                        ],
                        "total_look_duration_ms": 534,
                        "age_group": "20-29",
                        "gender": "male"
                    }
                ]
            }
        }
    )


# ── 응답용 ────────────────────────────────────────────────────────────────────

class EventBatchResponse(BaseModel):
    inserted: int = Field(..., description="저장된 track 행 수")
    status:   str = "success"


# ── GET /events/ 응답 ─────────────────────────────────────────────────────────

class EventRawResponse(BaseModel):
    id:                     str
    ts:                     datetime
    device_id:              str
    campaign_id:            str
    track_id:               int
    exposure_start_ms:      int
    exposure_end_ms:        int
    exposure_ms:            int
    look_times:             list
    total_look_duration_ms: int
    age_group:              Optional[str]
    gender:                 Optional[str]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "device_id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)


class EventListResponse(BaseModel):
    events: List[EventRawResponse]
    total:  int

# ── GET /stats/ 응답 ──────────────────────────────────────────────────────────

class AggBase(BaseModel):
    """공통 집계 필드"""
    exposure_count:           int
    avg_dwell_time_ms:        float
    interested_count:         int
    attention_rate_tracks:    float
    total_attention_time_ms:  float
    attention_rate_times:     float
    count_10s:                int
    count_20s:                int
    count_30s:                int
    count_40s:                int
    count_50s_plus:           int
    count_60s_plus:           int
    count_male:               int
    count_female:             int

    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v) if hasattr(v, 'hex') else v


# class DailyAggResponse(AggBase):
#     id:          int
#     date:        date
#     device_id:   str
#     campaign_id: str
#     created_at:  datetime
#     updated_at:  datetime

#     @field_validator("device_id", "campaign_id", mode="before")
#     @classmethod
#     def uuid_to_str(cls, v):
#         return str(v)


# class DailyAggListResponse(BaseModel):
#     results: List[DailyAggResponse]
#     total:   int


# class HourlyAggResponse(AggBase):
#     id:          int
#     hour:        datetime
#     device_id:   str
#     campaign_id: str
#     created_at:  datetime
#     updated_at:  datetime

#     @field_validator("device_id", "campaign_id", mode="before")
#     @classmethod
#     def uuid_to_str(cls, v):
#         return str(v)


# class HourlyAggListResponse(BaseModel):
#     results: List[HourlyAggResponse]
#     total:   int


class CampaignAggResponse(AggBase):
    id:          int
    device_id:   str
    campaign_id: str
    created_at:  datetime
    updated_at:  datetime
    
    # 고급 지표
    avg_revisit_count:       float
    avg_fixation_latency_ms: Optional[float]
    viewability_score:       float
    avg_attention_time_ms:   float
    peak_hour:               Optional[int]
    target_match_rate:       Optional[float]
    sov:                     Optional[float] # sov
    attention_track_efficiency: Optional[float] # 사람 수 기준 점유율 대비 효율
    attention_time_efficiency:  Optional[float] # 시간 기준 점유율 대비 효율
    @field_validator("device_id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)


class CampaignAggListResponse(BaseModel):
    results: List[CampaignAggResponse]
    total:   int


# ── 광고 신청 (Apply) ──────────────────────────────────────────────────────────

class SlotItemSchema(BaseModel):
    length: Optional[int] = None
    mine: bool

class SlotConfigSchema(BaseModel):
    adLength: Optional[int] = None
    slots: List[SlotItemSchema]

class AddressItemSchema(BaseModel):
    addr: str
    label: str

class ApplicationCreate(BaseModel):
    brand:        str
    company:      str
    category:     str
    start_date:   date
    end_date:     date
    start_time:   str        # "HH:MM"
    end_time:     str        # "HH:MM"
    slot_configs: List[SlotConfigSchema]
    placement:    str
    addresses:    List[AddressItemSchema]
    age:          str        # 단일 값 (예: "20-29") 또는 "all"
    gender:       str        # "all" | "m" | "f"
    name:         str
    phone:        str
    email:        str

class ApplicationResponse(BaseModel):
    id:         str
    name:       str
    status:     str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)

    @field_validator("status", mode="before")
    @classmethod
    def enum_to_str(cls, v):
        return v.value if hasattr(v, "value") else v


class DbscanInfo(BaseModel):
    eps:           float
    min_samples:   int
    cluster_count: int
    noise_count:   int


class GoldenZoneCluster(BaseModel):
    label:       int
    point_count: int
    points:      Optional[list] = None


class GoldenZoneResponse(BaseModel):
    campaign_id: str
    device_id:   str
    computed_at: datetime
    point_count: int
    event_count: int
    dbscan:      DbscanInfo
    clusters:    List[GoldenZoneCluster]


# ── 인증 ─────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"


class SendCodeRequest(BaseModel):
    email: str


class LoginRequest(BaseModel):
    email:    str
    password: str


class UserCreate(BaseModel):
    email:    str
    password: str
    code:     str


class UserResponse(BaseModel):
    id:         str
    email:      str
    role:       str
    is_active:  bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)

    @field_validator("role", mode="before")
    @classmethod
    def role_to_str(cls, v):
        return v.value if hasattr(v, "value") else v

# ── GET /stats/range/ 응답 ────────────────────────────────────────────────────

class HourlyTrend(BaseModel):
    hour:             str
    exposure_count:   int
    interested_count: int


class DailyTrend(BaseModel):
    date:             str
    exposure_count:   int
    interested_count: int
    total_dwell_ms:   int
    total_attention_ms: int
    attention_track_efficiency : Optional[float] = None
    attention_time_efficiency:  Optional[float] = None


# ── GET /stats/distribution/ 응답 ────────────────────────────────────────────

class DistributionBucket(BaseModel):
    bucket:         str
    dwell_count:    int
    fixation_count: int


class DistributionResponse(BaseModel):
    buckets: List[DistributionBucket]


# ── GET /campaigns/ 응답 ─────────────────────────────────────────────────────

class DeviceSimple(BaseModel):
    id:     str
    name:   str
    status: str

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)

    @field_validator("status", mode="before")
    @classmethod
    def enum_to_str(cls, v):
        return v.value if hasattr(v, "value") else v


class CampaignWithDevices(BaseModel):
    id:         str
    name:       str
    status:     str
    start_date: date
    end_date:   date
    devices:    List[DeviceSimple]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)

    @field_validator("status", mode="before")
    @classmethod
    def enum_to_str(cls, v):
        return v.value if hasattr(v, "value") else v


class CampaignListResponse(BaseModel):
    results: List[CampaignWithDevices]
    total:   int


class RangeStatsResponse(AggBase):
    start_date:  str
    end_date:    str
    device_id:   str
    campaign_id: str

    # 관심 인구 성별·연령 분포
    interested_count_male:     int
    interested_count_female:   int
    interested_count_10s:      int
    interested_count_20s:      int
    interested_count_30s:      int
    interested_count_40s:      int
    interested_count_50s_plus: int
    interested_count_60s_plus: int

    # 고급 지표
    avg_revisit_count:       float
    avg_fixation_latency_ms: Optional[float]
    viewability_score:       float
    avg_attention_time_ms:   float
    peak_hour:               Optional[int]
    target_match_rate:       Optional[float]
    sov :                     Optional[float]
    attention_track_efficiency : Optional[float] = None
    attention_time_efficiency  : Optional[float] = None

    # 추이
    hourly_trend: List[HourlyTrend]
    daily_trend:  List[DailyTrend]
    distribution: List[DistributionBucket]

class CampaignCreate(BaseModel):
    name:             str
    start_date:       date
    end_date:         date
    target_age_group: Optional[str] = None
    target_gender:    Optional[str] = None




# ── 설정 변경 요청 ─────────────────────────────────────────────────────────────

class ChangeRequestCreate(BaseModel):
    campaign_id:      str
    target_gender:    Optional[Literal["male", "female"]] = None
    target_age_group: Optional[Literal["10-19", "20-29", "30-39", "40-49", "50-59", "60+"]] = None
    start_date:       Optional[date] = None
    end_date:         Optional[date] = None
    broadcast_start:  Optional[str] = None
    broadcast_end:    Optional[str] = None
    reason:           Optional[str] = None


class ChangeRequestResponse(BaseModel):
    id:              str
    campaign_id:     str
    campaign_name:   str
    status:          str
    target_gender:   Optional[str]
    target_age_group: Optional[str]
    start_date:      Optional[date]
    end_date:        Optional[date]
    broadcast_start: Optional[str]
    broadcast_end:   Optional[str]
    reason:          Optional[str]
    created_at:      datetime
    reviewed_at:     Optional[datetime]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)

    @field_validator("status", mode="before")
    @classmethod
    def enum_to_str(cls, v):
        return v.value if hasattr(v, "value") else v


class ChangeRequestListResponse(BaseModel):
    results: List[ChangeRequestResponse]
    total:   int
