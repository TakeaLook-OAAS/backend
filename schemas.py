from pydantic import BaseModel, Field, ConfigDict, computed_field
from datetime import datetime
from typing import Optional, List, Any
import uuid


# ── AI팀 JSON 내부 구조 ──────────────────────────────────────────────────────

class SegmentData(BaseModel):
    """배치 메타데이터"""
    device_id:   str       # 기기 UUID (segment 안에 포함됨)
    index:       int       # 배치 인덱스
    cycle_index: int       # 이 기기에서 몇 번째 광고인지
    timestamp:   datetime  # 배치 기준 시각 (ts로 저장)
    duration_ms: int       # 배치 지속 시간 (ms)
    roi_polygon: Optional[List[List[int]]] = None  # ROI 폴리곤 좌표 4점 [[x,y], ...]


class ExposureData(BaseModel):
    start_ms: int
    end_ms:   int
    # exposure_ms 제거 — 백엔드에서 end_ms - start_ms로 계산

    @computed_field
    @property
    def exposure_ms(self) -> int:
        return self.end_ms - self.start_ms


class LookTime(BaseModel):
    start_ms: int
    end_ms:   int
    # duration_ms 제거 — 백엔드에서 end_ms - start_ms로 계산

    @computed_field
    @property
    def duration_ms(self) -> int:
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
    segment: SegmentData                                               # 배치 메타데이터
    tracks:  List[TrackData] = Field(..., description="track 목록")   # track 목록

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "segment": {
                    "device_id":   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                    "index":       0,
                    "cycle_index": 0,
                    "timestamp":   "2026-03-27T09:34:00.688523+00:00",
                    "duration_ms": 2000,
                    "roi_polygon": [[0,0],[1920,0],[1920,1080],[0,1080]]
                },
                "tracks": [
                    {
                        "track_id": 1,
                        "exposure": {"start_ms": 0, "end_ms": 2040},
                        "look_times": [],
                        "total_look_duration_ms": 0,
                        "age_group": "30-39",
                        "gender": "female"
                    }
                ]
            }
        }
    )


# ── 응답용 ────────────────────────────────────────────────────────────────────

class EventBatchResponse(BaseModel):
    """배치 수신 결과 응답"""
    inserted: int = Field(..., description="저장된 track 행 수")
    status:   str = "success"


class EventRawOut(BaseModel):
    """events_raw 단일 행 응답 (GET 조회용)"""
    model_config = ConfigDict(from_attributes=True)  # ORM 객체 → Pydantic 변환 허용

    id:                    uuid.UUID
    ts:                    datetime
    ingested_at:           datetime
    device_id:             uuid.UUID
    campaign_id:           uuid.UUID
    track_id:              int
    exposure_start_ms:     int
    exposure_end_ms:       int
    exposure_ms:           int
    look_times:            Any           # JSONB 원본 그대로 반환
    total_look_duration_ms: int
    age_group:             Optional[str]
    gender:                Optional[str]


class EventListResponse(BaseModel):
    """이벤트 목록 조회 응답"""
    events: List[EventRawOut]
    total:  int              = Field(..., description="반환된 이벤트 수")