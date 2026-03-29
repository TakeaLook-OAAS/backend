import logging
import uuid
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models, schemas

router = APIRouter()
logger = logging.getLogger(__name__)

# 배치 주기 (분) — ts와 ingested_at 차이가 이 값보다 크면 경고
BATCH_INTERVAL_MINUTES = 10

# age_group 정규화 — AI팀이 "unknown"으로 보내는 경우 None으로 변환
VALID_AGE_GROUPS = {"10-19", "20-29", "30-39", "40-49", "50-59"}

def _normalize_age_group(age_group: str | None) -> str | None:
    """
    AI팀이 보내는 age_group을 정규화합니다.
    - None → None
    - "unknown" → None (분석 불가 케이스)
    - 유효한 값 ("10-19" 등) → 그대로 반환
    """
    if age_group is None or age_group not in VALID_AGE_GROUPS:
        return None
    return age_group


@router.post("/", response_model=schemas.EventBatchResponse)
def create_events(event_in: schemas.EventBatchCreate, db: Session = Depends(get_db)):
    """
    AI팀 배치 수신 API
    - segment 메타데이터를 segment_logs 테이블에 저장
    - tracks 배열을 풀어 track 1개 → events_raw 1행으로 저장
    - device_id + cycle_index → campaign_id 조회 (device_campaigns 테이블)
    - age_group "unknown" → None으로 정규화
    - ts와 ingested_at 차이가 배치 주기(10분) 초과 시 경고 로그
    """
    # segment에서 device_id 파싱
    try:
        device_id = uuid.UUID(event_in.segment.device_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"UUID 형식 오류: {e}")

    # device_id + cycle_index로 campaign_id 조회
    device_campaign = (
        db.query(models.DeviceCampaign)
        .filter_by(device_id=device_id, cycle_index=event_in.segment.cycle_index)
        .first()
    )
    if not device_campaign:
        raise HTTPException(
            status_code=404,
            detail=f"device_id={device_id}, cycle_index={event_in.segment.cycle_index}에 해당하는 캠페인이 없습니다."
        )
    campaign_id = device_campaign.campaign_id

    # ts 추출 (segment.timestamp)
    ts = event_in.segment.timestamp

    # 배치 지연 감지 — ingested_at은 지금 시각으로 추정
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    diff = now - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else now - ts
    if diff > timedelta(minutes=BATCH_INTERVAL_MINUTES):
        logger.warning(
            f"배치 지연 감지 | ts={ts} | ingested_at≈{now} | 지연={diff}"
        )

    # segment_logs 테이블에 배치 메타데이터 저장
    segment_log = models.SegmentLog(
        ts          = ts,
        device_id   = device_id,
        campaign_id = campaign_id,
        index       = event_in.segment.index,
        cycle_index = event_in.segment.cycle_index,
        duration_ms = event_in.segment.duration_ms,
        roi_polygon = event_in.segment.roi_polygon,
    )

    # events_raw에 track 단위로 저장
    rows = [
        models.EventRaw(
            ts                     = ts,
            device_id              = device_id,
            campaign_id            = campaign_id,
            track_id               = track.track_id,
            exposure_start_ms      = track.exposure.start_ms,
            exposure_end_ms        = track.exposure.end_ms,
            exposure_ms            = track.exposure.exposure_ms,  # computed_field
            look_times             = [{"start_ms": lt.start_ms, "end_ms": lt.end_ms} for lt in track.look_times],
            total_look_duration_ms = track.total_look_duration_ms,
            age_group              = _normalize_age_group(track.age_group),  # unknown → None
            gender                 = track.gender,
        )
        for track in event_in.tracks
    ]

    try:
        db.add(segment_log)
        db.add_all(rows)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB 저장 실패: {e}")

    return schemas.EventBatchResponse(inserted=len(rows))