from pydantic import BaseModel, Field, ConfigDict, computed_field
from datetime import datetime, date
from typing import Optional, List
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


class DailyAggResponse(AggBase):
    id:          int
    date:        date
    device_id:   str
    campaign_id: str
    created_at:  datetime
    updated_at:  datetime

    @field_validator("device_id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)


class DailyAggListResponse(BaseModel):
    results: List[DailyAggResponse]
    total:   int


class HourlyAggResponse(AggBase):
    id:          int
    hour:        datetime
    device_id:   str
    campaign_id: str
    created_at:  datetime
    updated_at:  datetime

    @field_validator("device_id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)


class HourlyAggListResponse(BaseModel):
    results: List[HourlyAggResponse]
    total:   int


class CampaignAggResponse(AggBase):
    id:          int
    device_id:   str
    campaign_id: str
    created_at:  datetime
    updated_at:  datetime

    @field_validator("device_id", "campaign_id", mode="before")
    @classmethod
    def uuid_to_str(cls, v):
        return str(v)


class CampaignAggListResponse(BaseModel):
    results: List[CampaignAggResponse]
    total:   int


class BoxStatsResponse(AggBase):
    campaign_id:    str
    device_id:      str
    matched_tracks: int

    model_config = ConfigDict(from_attributes=False)


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