import logging
import uuid
from datetime import timedelta, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
import models, schemas
from enums import DeviceStatus

router = APIRouter()
logger = logging.getLogger(__name__)

# 배치 주기 (분) — ts와 ingested_at 차이가 이 값보다 크면 경고 로그
BATCH_INTERVAL_MINUTES = 10

# 유효한 age_group 값 목록 — 이 외의 값("unknown" 포함)은 None으로 변환
VALID_AGE_GROUPS = {"10-19", "20-29", "30-39", "40-49", "50-59"}


def _normalize_age_group(age_group: str | None) -> str | None:
    """
    AI팀이 보내는 age_group을 정규화합니다.
    - None → None
    - "unknown" 또는 유효하지 않은 값 → None (분석 불가 케이스)
    - 유효한 값 ("10-19" 등) → 그대로 반환
    """
    if age_group is None or age_group not in VALID_AGE_GROUPS:
        return None
    return age_group


def _validate_device(device_id: uuid.UUID, db: Session) -> models.Device:
    """
    device_id로 기기를 조회하고 활성 상태인지 확인합니다.
    - 기기가 DB에 없으면 401 (미등록 기기 = 인증 실패)
    - 기기가 DISABLE 또는 MAINTENANCE 상태면 403 (비활성화 기기)
    """
    device = db.query(models.Device).filter_by(id=device_id).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="등록되지 않은 기기입니다. device_id를 확인하세요.",
        )
    if device.status != DeviceStatus.ENABLE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"비활성화된 기기입니다 (현재 상태: {device.status}).",
        )
    return device


# ── POST /events/ ─────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=schemas.EventBatchResponse,
    status_code=202,  # 202 Accepted — 명세서 기준
    summary="Raw event 수집",
    description="AI 기기에서 보내는 배치 데이터를 수신해 DB에 저장합니다.",
)
def create_events(event_in: schemas.EventBatchCreate, db: Session = Depends(get_db)):
    """
    AI기기 배치 수신 API:
    1. device_id UUID 파싱 (형식 오류 → 400)
    2. 기기 존재 및 활성화 확인 (미등록 → 401, 비활성화 → 403)
    3. device_id + cycle_index로 campaign_id 조회 (없으면 404)
    4. 배치 지연 감지 (ts 기준 10분 초과 시 경고 로그)
    5. segment_logs + events_raw에 저장 (중복 → 409)
    """

    # ① device_id 파싱 — UUID 형식 오류면 400
    try:
        device_id = uuid.UUID(event_in.segment.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 형식 오류: {e}")

    # ③ 기기 존재 및 활성화 확인 (401 / 403)
    _validate_device(device_id, db)

    # ④ device_id + cycle_index로 campaign_id 조회
    device_campaign = (
        db.query(models.DeviceCampaign)
        .filter_by(device_id=device_id, cycle_index=event_in.segment.cycle_index)
        .first()
    )
    if not device_campaign:
        raise HTTPException(
            status_code=404,
            detail=(
                f"device_id={device_id}, "
                f"cycle_index={event_in.segment.cycle_index}에 해당하는 캠페인이 없습니다."
            ),
        )
    campaign_id = device_campaign.campaign_id

    # ⑤ 배치 기준 시각 추출 및 지연 감지
    ts_raw = event_in.segment.timestamp
    # naive datetime이면 UTC로 고정 (DB 세션 타임존 의존 방지)
    ts = ts_raw.replace(tzinfo=timezone.utc) if ts_raw.tzinfo is None else ts_raw
    now = datetime.now(timezone.utc)
    diff = now - ts
    if diff > timedelta(minutes=BATCH_INTERVAL_MINUTES):
        logger.warning(
            "배치 지연 감지 | ts=%s | ingested_at≈%s | 지연=%s", ts, now, diff
        )

    # ⑥-a. segment_logs에 배치 메타데이터 저장
    segment_log = models.SegmentLog(
        ts          = ts,
        device_id   = device_id,
        campaign_id = campaign_id,
        index       = event_in.segment.index,
        cycle_index = event_in.segment.cycle_index,
        duration_ms = event_in.segment.duration_ms,
        roi_polygon = event_in.segment.roi_polygon,
    )

    # ⑥-b. events_raw에 track 단위로 저장 (track 1개 → 1행)
    rows = [
        models.EventRaw(
            ts                     = ts,
            device_id              = device_id,
            campaign_id            = campaign_id,
            track_id               = track.track_id,
            exposure_start_ms      = track.exposure.start_ms,
            exposure_end_ms        = track.exposure.end_ms,
            exposure_ms            = track.exposure.exposure_ms,   # end - start
            look_times             = [
                {"start_ms": lt.start_ms, "end_ms": lt.end_ms}
                for lt in track.look_times
            ],
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
    except IntegrityError as e:
        db.rollback()
        # 중복 제약(uq_event_raw_track)만 409로 분류, 나머지는 500
        if "uq_event_raw_track" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 저장된 이벤트가 포함되어 있습니다 (device_id + track_id + ts 중복).",
            )
        logger.error("DB 저장 중 무결성 오류: %s", e.orig)
        raise HTTPException(status_code=500, detail="DB 저장 중 오류가 발생했습니다.")
    except Exception as e:
        db.rollback()
        logger.error("DB 저장 실패: %s", e)
        raise HTTPException(status_code=500, detail="DB 저장 중 오류가 발생했습니다.")

    return schemas.EventBatchResponse(inserted=len(rows))


# ── GET /events/ ──────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=schemas.EventListResponse,
    summary="Raw event 조회",
    description="저장된 raw event 목록을 조회합니다. device_id / campaign_id로 필터링 가능합니다.",
)
def list_events(
    device_id:   uuid.UUID | None = None,   # 특정 기기 데이터만 조회
    campaign_id: uuid.UUID | None = None,   # 특정 캠페인 데이터만 조회
    limit:       int = Query(default=100, ge=1, le=1000),  # 최대 반환 행 수 (1~1000)
    db: Session = Depends(get_db),
):
    """
    Raw event 조회 API:
    - device_id, campaign_id 쿼리 파라미터로 필터링
    - ts 내림차순 (최신 데이터 우선)
    - limit으로 반환 행 수 제한
    """
    query = db.query(models.EventRaw)

    # 기기 필터 적용
    if device_id:
        query = query.filter(models.EventRaw.device_id == device_id)

    # 캠페인 필터 적용
    if campaign_id:
        query = query.filter(models.EventRaw.campaign_id == campaign_id)

    # 최신순 정렬 후 limit 적용
    rows = query.order_by(models.EventRaw.ts.desc()).limit(limit).all()

    return schemas.EventListResponse(events=rows, total=len(rows))
