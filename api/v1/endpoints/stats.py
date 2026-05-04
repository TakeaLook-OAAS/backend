import uuid

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
import models, schemas
from Aggregation import _build_agg_counts
from analysis.golden_zone import run_golden_zone

router = APIRouter()

SCREEN_W = 1280.0
SCREEN_H = 720.0


def _empty_box_counts() -> dict:
    return {
        "exposure_count": 0, "avg_dwell_time_ms": 0.0, "interested_count": 0,
        "attention_rate_tracks": 0.0, "total_attention_time_ms": 0.0,
        "attention_rate_times": 0.0, "count_10s": 0, "count_20s": 0,
        "count_30s": 0, "count_40s": 0, "count_50s_plus": 0,
        "count_60s_plus": 0, "count_male": 0, "count_female": 0,
    }


# ── GET /stats/daily/ ─────────────────────────────────────────────────────────

@router.get(
    "/daily/",
    response_model=schemas.DailyAggListResponse,
    summary="일별 집계 조회",
)
def get_daily_aggs(
    device_id:   Optional[uuid.UUID] = None,
    campaign_id: Optional[uuid.UUID] = None,
    start_date:  Optional[date]      = None,
    end_date:    Optional[date]      = None,
    target_date: Optional[date]      = None,  # 특정 날짜
    limit:       int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(models.DailyAgg)

    if device_id:
        query = query.filter(models.DailyAgg.device_id == device_id)
    if campaign_id:
        query = query.filter(models.DailyAgg.campaign_id == campaign_id)
    if target_date:
        query = query.filter(models.DailyAgg.date == target_date)
    else:
        if start_date:
            query = query.filter(models.DailyAgg.date >= start_date)
        if end_date:
            query = query.filter(models.DailyAgg.date <= end_date)

    rows = query.order_by(models.DailyAgg.date.desc()).limit(limit).all()
    return schemas.DailyAggListResponse(results=rows, total=len(rows))


# ── GET /stats/hourly/ ────────────────────────────────────────────────────────

@router.get(
    "/hourly/",
    response_model=schemas.HourlyAggListResponse,
    summary="시간별 집계 조회",
)
def get_hourly_aggs(
    device_id:   Optional[uuid.UUID] = None,
    campaign_id: Optional[uuid.UUID] = None,
    start_date:  Optional[date]      = None,
    end_date:    Optional[date]      = None,
    target_date: Optional[date]      = None,
    limit:       int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(models.HourlyAgg)

    if device_id:
        query = query.filter(models.HourlyAgg.device_id == device_id)
    if campaign_id:
        query = query.filter(models.HourlyAgg.campaign_id == campaign_id)
    if target_date:
        query = query.filter(
            models.HourlyAgg.hour >= target_date,
            models.HourlyAgg.hour  < target_date + timedelta(days=1),
        )
    else:
        if start_date:
            query = query.filter(models.HourlyAgg.hour >= start_date)
        if end_date:
            query = query.filter(models.HourlyAgg.hour  < end_date + timedelta(days=1))

    rows = query.order_by(models.HourlyAgg.hour.desc()).limit(limit).all()
    return schemas.HourlyAggListResponse(results=rows, total=len(rows))


# ── GET /stats/campaign/ ──────────────────────────────────────────────────────

@router.get(
    "/campaign/",
    response_model=schemas.CampaignAggListResponse,
    summary="캠페인 전체 집계 조회",
)
def get_campaign_aggs(
    device_id:   Optional[uuid.UUID] = None,
    campaign_id: Optional[uuid.UUID] = None,
    limit:       int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(models.CampaignAgg)

    if device_id:
        query = query.filter(models.CampaignAgg.device_id == device_id)
    if campaign_id:
        query = query.filter(models.CampaignAgg.campaign_id == campaign_id)

    rows = query.order_by(models.CampaignAgg.id.desc()).limit(limit).all()
    return schemas.CampaignAggListResponse(results=rows, total=len(rows))

# --- 박스 필터 집계 ──────────────────────────────────────────────

@router.get(
    "/box/",
    response_model=schemas.BoxStatsResponse,
    summary="박스 필터 집계",
)
def get_box_stats(
    campaign_id: uuid.UUID,
    device_id:   uuid.UUID,
    x_min: float = Query(..., ge=0.0, le=100.0),
    y_min: float = Query(..., ge=0.0, le=100.0),
    x_max: float = Query(..., ge=0.0, le=100.0),
    y_max: float = Query(..., ge=0.0, le=100.0),
    db: Session = Depends(get_db),
):
    px_x_min = (x_min / 100.0) * SCREEN_W
    px_x_max = (x_max / 100.0) * SCREEN_W
    px_y_min = (y_min / 100.0) * SCREEN_H
    px_y_max = (y_max / 100.0) * SCREEN_H

    all_rows = (
        db.query(models.EventRaw)
        .filter(
            models.EventRaw.campaign_id == campaign_id,
            models.EventRaw.device_id   == device_id,
        )
        .all()
    )

    def in_box(event) -> bool:
        for lt in (event.look_times or []):
            sc = lt.get("start_center")
            ec = lt.get("end_center")
            if sc and px_x_min <= sc[0] <= px_x_max and px_y_min <= sc[1] <= px_y_max:
                return True
            if ec and px_x_min <= ec[0] <= px_x_max and px_y_min <= ec[1] <= px_y_max:
                return True
        return False

    filtered = [r for r in all_rows if in_box(r)]
    counts   = _build_agg_counts(filtered) if filtered else _empty_box_counts()

    return schemas.BoxStatsResponse(
        campaign_id    = str(campaign_id),
        device_id      = str(device_id),
        matched_tracks = len(filtered),
        **counts,
    )


# --- DBSCAN ──────────────────────────────────────────────────────

@router.get(
    "/golden-zone/",
    response_model=schemas.GoldenZoneResponse,
    summary="골든존 조회",
    description=(
        "dbscan_aggs에 저장된 클러스터 결과를 반환합니다. "
        "매일 자정 run_all_aggregations()가 자동으로 갱신합니다. "
        "x_min/y_min/x_max/y_max (0-100%) 지정 시 해당 박스 안 포인트만 반환합니다."
    ),
)
def get_golden_zone(
    campaign_id: uuid.UUID,
    device_id:   uuid.UUID,
    x_min: Optional[float] = None,
    y_min: Optional[float] = None,
    x_max: Optional[float] = None,
    y_max: Optional[float] = None,
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    db: Session = Depends(get_db),
):
    has_box = all(v is not None for v in [x_min, y_min, x_max, y_max])

    def apply_box_filter(clusters_data: list, is_raw: bool) -> list:
        if not has_box:
            if is_raw:
                return [
                    schemas.GoldenZoneCluster(label=c["label"], point_count=c["point_count"], points=c["points"])
                    for c in clusters_data
                ]
            return [
                schemas.GoldenZoneCluster(label=row.cluster_label, point_count=row.cluster_point_count, points=row.points)
                for row in clusters_data
            ]

        px_x_min = (x_min / 100.0) * SCREEN_W
        px_x_max = (x_max / 100.0) * SCREEN_W
        px_y_min = (y_min / 100.0) * SCREEN_H
        px_y_max = (y_max / 100.0) * SCREEN_H

        def in_box(p):
            return px_x_min <= p[0] <= px_x_max and px_y_min <= p[1] <= px_y_max

        if is_raw:
            return [
                schemas.GoldenZoneCluster(
                    label=c["label"],
                    points=[p for p in (c["points"] or []) if in_box(p)],
                    point_count=len([p for p in (c["points"] or []) if in_box(p)]),
                )
                for c in clusters_data
            ]
        return [
            schemas.GoldenZoneCluster(
                label=row.cluster_label,
                points=[p for p in (row.points or []) if in_box(p)],
                point_count=len([p for p in (row.points or []) if in_box(p)]),
            )
            for row in clusters_data
        ]

    # ── 날짜 범위 지정: events_raw에서 직접 DBSCAN 실행 ───────────────────────
    if start_date or end_date:
        query = (
            db.query(models.EventRaw)
            .filter(
                models.EventRaw.campaign_id == campaign_id,
                models.EventRaw.device_id   == device_id,
                func.jsonb_array_length(models.EventRaw.look_times) > 0,
            )
        )
        if start_date:
            query = query.filter(
                func.date(func.timezone("Asia/Seoul", models.EventRaw.ts)) >= start_date
            )
        if end_date:
            query = query.filter(
                func.date(func.timezone("Asia/Seoul", models.EventRaw.ts)) <= end_date
            )

        rows = query.all()
        if not rows:
            raise HTTPException(status_code=404, detail="해당 기간에 look_times 데이터가 없습니다.")

        result = run_golden_zone(rows=rows, eps=100.0, min_samples=10, n_interp=5)
        if result["status"] != "ok":
            raise HTTPException(
                status_code=404,
                detail=result.get("detail", f"클러스터를 찾을 수 없습니다: {result['status']}"),
            )

        return schemas.GoldenZoneResponse(
            campaign_id = str(campaign_id),
            device_id   = str(device_id),
            computed_at = datetime.now(timezone.utc),
            point_count = result["point_count"],
            event_count = result["event_count"],
            dbscan      = schemas.DbscanInfo(
                eps           = 100.0,
                min_samples   = 10,
                cluster_count = result["dbscan"]["cluster_count"],
                noise_count   = result["dbscan"]["noise_count"],
            ),
            clusters = apply_box_filter(result["clusters"], is_raw=True),
        )

    # ── 날짜 없음: dbscan_aggs 저장값 반환 ────────────────────────────────────
    agg_rows = (
        db.query(models.DbscanAgg)
        .filter_by(campaign_id=campaign_id, device_id=device_id)
        .order_by(models.DbscanAgg.cluster_point_count.desc())
        .all()
    )

    if not agg_rows:
        raise HTTPException(
            status_code=404,
            detail="저장된 골든존 결과가 없습니다. 집계가 아직 실행되지 않았습니다.",
        )

    first = agg_rows[0]
    return schemas.GoldenZoneResponse(
        campaign_id = str(campaign_id),
        device_id   = str(device_id),
        computed_at = first.computed_at,
        point_count = first.point_count,
        event_count = first.event_count,
        dbscan      = schemas.DbscanInfo(
            eps           = first.eps,
            min_samples   = first.min_samples,
            cluster_count = first.cluster_count,
            noise_count   = first.noise_count,
        ),
        clusters = apply_box_filter(agg_rows, is_raw=False),
    )
