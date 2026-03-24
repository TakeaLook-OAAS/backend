import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
 
router = APIRouter()
 
 
@router.post("/", response_model=schemas.EventBatchResponse)
def create_events(event_in: schemas.EventBatchCreate, db: Session = Depends(get_db)):
    """
    AI팀 배치 수신 API
    - tracks 배열을 풀어 track 1개 → events_raw 1행으로 저장
    - ingested_at은 DB에서 server_default=func.now()로 자동 기록
    """
    try:
        device_id   = uuid.UUID(event_in.device_id)
        roi_id      = uuid.UUID(event_in.roi_id)
        campaign_id = uuid.UUID(event_in.campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"UUID 형식 오류: {e}")
 
    rows = [
        models.EventRaw(
            device_id=device_id,
            roi_id=roi_id,
            campaign_id=campaign_id,
            # ts 제거 — ingested_at은 DB server_default로 자동 기록
            track_id=track.track_id,
            exposure_start_ms=track.exposure.start_ms,
            exposure_end_ms=track.exposure.end_ms,
            exposure_dwell_ms=track.exposure.dwell_ms,
            look_times=[lt.model_dump() for lt in track.look_times],
            total_look_duration_ms=track.total_look_duration_ms,
            age_group=track.age_group,
            gender=track.gender,
        )
        for track in event_in.tracks
    ]
 
    try:
        db.add_all(rows)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB 저장 실패: {e}")
 
    return schemas.EventBatchResponse(inserted=len(rows))
 