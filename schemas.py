from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
 
 
# ── AI팀 JSON 내부 구조 ──────────────────────────────────────────────────────
 
class ExposureData(BaseModel):
    start_ms: int
    end_ms: int
    dwell_ms: int
 
 
class LookTime(BaseModel):
    start_ms: int
    end_ms: int
    duration_ms: int
 
 
class TrackData(BaseModel):
    track_id: int
    exposure: ExposureData
    look_times: List[LookTime]
    total_look_duration_ms: int
    age_group: Optional[str] = None
    gender: Optional[str] = None
 
 
# ── 수신용 (요청 바디) ────────────────────────────────────────────────────────
 
class EventBatchCreate(BaseModel):
    """AI팀에서 한 번에 보내는 배치 단위 요청"""
    device_id:   str = Field(..., description="기기 UUID")
    roi_id:      str = Field(..., description="ROI UUID")
    campaign_id: str = Field(..., description="캠페인 UUID")
    # ts 제거 — 서버 수신 시각(ingested_at)을 DB에서 자동 기록
    tracks: List[TrackData] = Field(..., description="track 목록 (각각 1행으로 저장)")
 
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "device_id":   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "roi_id":      "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "campaign_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "tracks": [
                    {
                        "track_id": 1,
                        "exposure": {"start_ms": 222, "end_ms": 161292, "dwell_ms": 161070},
                        "look_times": [
                            {"start_ms": 7631, "end_ms": 8589, "duration_ms": 958}
                        ],
                        "total_look_duration_ms": 42547,
                        "age_group": "adult",
                        "gender": "male"
                    }
                ]
            }
        }
    )
 
 
# ── 응답용 ────────────────────────────────────────────────────────────────────
 
class EventBatchResponse(BaseModel):
    inserted: int = Field(..., description="저장된 track 행 수")
    status: str = "success"