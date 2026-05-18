import uuid

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from database.database import get_db
import database.models as models, database.schemas as schemas
from Aggregation.golden_zone import run_golden_zone

router = APIRouter()

KST = timezone(timedelta(hours=9))


# # ── GET /stats/daily/ ─────────────────────────────────────────────────────────

# @router.get("/daily/", response_model=schemas.DailyAggListResponse, summary="일별 집계 조회")
# def get_daily_aggs(...): ...


# # ── GET /stats/hourly/ ────────────────────────────────────────────────────────

# @router.get("/hourly/", response_model=schemas.HourlyAggListResponse, summary="시간별 집계 조회")
# def get_hourly_aggs(...): ...


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


# ── GET /stats/golden-zone/ ───────────────────────────────────────────────────

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
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    db: Session = Depends(get_db),
):
    # 날짜 범위 지정: events_raw에서 직접 DBSCAN 실행
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
            start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=KST)
            query = query.filter(models.EventRaw.ts >= start_dt)
        if end_date:
            end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=KST) + timedelta(days=1)
            query = query.filter(models.EventRaw.ts < end_dt)

        rows = query.all()
        if not rows:
            raise HTTPException(status_code=404, detail="해당 기간에 look_times 데이터가 없습니다.")

        result = run_golden_zone(rows=rows, eps=100.0, min_samples=50, n_interp=2)
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
            clusters = [
                schemas.GoldenZoneCluster(label=c["label"], point_count=c["point_count"], points=c["points"])
                for c in result["clusters"]
            ],
        )

    # 날짜 없음: dbscan_aggs 저장값 반환
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
        clusters = [
            schemas.GoldenZoneCluster(label=row.cluster_label, point_count=row.cluster_point_count, points=row.points)
            for row in agg_rows
        ],
    )


# ── GET /stats/range/ ─────────────────────────────────────────────────────────

@router.get(
    "/range/",
    response_model=schemas.RangeStatsResponse,
    summary="기간별 집계 조회",
    description="daily_aggs / hourly_aggs 사전 집계 테이블 기반으로 빠르게 반환합니다.",
)
def get_range_stats(
    start_date:  date,
    end_date:    date,
    device_id:   uuid.UUID,
    campaign_id: uuid.UUID,
    age_group:   Optional[str] = None,
    gender:      Optional[str] = None,
    db: Session = Depends(get_db),
):
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date는 end_date보다 클 수 없습니다.")

    if not db.query(models.DeviceCampaign).filter_by(device_id=device_id, campaign_id=campaign_id).first():
        raise HTTPException(status_code=404, detail="등록되지 않은 device-campaign 조합입니다.")

    # ── DailyAgg 조회 ────────────────────────────────────────────────────────
    daily_query = db.query(models.DailyAgg).filter(
        models.DailyAgg.device_id   == device_id,
        models.DailyAgg.campaign_id == campaign_id,
        models.DailyAgg.date >= start_date,
        models.DailyAgg.date <= end_date,
    )
    if age_group:
        daily_query = daily_query.filter(models.DailyAgg.age_group == age_group)
    if gender:
        daily_query = daily_query.filter(models.DailyAgg.gender == gender)

    daily_rows = daily_query.all()

    # ── 지표 계산 ─────────────────────────────────────────────────────────────
    total_exposure   = sum(r.exposure_count for r in daily_rows)
    total_interested = sum(r.interested_count for r in daily_rows)
    total_dwell     = sum(r.total_dwell_ms or 0 for r in daily_rows)
    total_attention = sum(r.total_attention_ms or 0 for r in daily_rows)

    avg_dwell_time_ms     = round(total_dwell / total_exposure, 2)       if total_exposure   > 0 else 0.0
    attention_rate_tracks = round(total_interested / total_exposure, 4)  if total_exposure   > 0 else 0.0
    attention_rate_times  = round(total_attention / total_dwell, 4)      if total_dwell      > 0 else 0.0
    avg_attention_time_ms = round(total_attention / total_interested, 2) if total_interested > 0 else 0.0
    viewability_score     = round(attention_rate_tracks * avg_attention_time_ms, 4)

    revisit_tracks    = sum(r.revisit_track_count for r in daily_rows)
    total_revisits    = sum(r.total_revisit_look_count for r in daily_rows)
    avg_revisit_count = round(total_revisits / revisit_tracks, 4) if revisit_tracks > 0 else 0.0

    lat_sum   = sum(r.total_fixation_latency_ms for r in daily_rows if r.total_fixation_latency_ms is not None)
    lat_count = sum(r.fixation_latency_count for r in daily_rows)
    avg_fixation_latency_ms = round(lat_sum / lat_count, 2) if lat_count > 0 else None

    matched_list      = [r.target_matched_count for r in daily_rows if r.target_matched_count is not None]
    target_match_rate = round(sum(matched_list) / total_interested, 4) if matched_list and total_interested > 0 else None

    count_10s      = sum(r.exposure_count for r in daily_rows if r.age_group == "10-19")
    count_20s      = sum(r.exposure_count for r in daily_rows if r.age_group == "20-29")
    count_30s      = sum(r.exposure_count for r in daily_rows if r.age_group == "30-39")
    count_40s      = sum(r.exposure_count for r in daily_rows if r.age_group == "40-49")
    count_50s_plus = sum(r.exposure_count for r in daily_rows if r.age_group == "50-59")
    count_60s_plus = sum(r.exposure_count for r in daily_rows if r.age_group == "60+")
    count_male     = sum(r.exposure_count for r in daily_rows if r.gender == "male")
    count_female   = sum(r.exposure_count for r in daily_rows if r.gender == "female")

    # ── HourlyAgg 조회 → hourly_trend + peak_hour ────────────────────────────
    hourly_query = db.query(models.HourlyAgg).filter(
        models.HourlyAgg.device_id   == device_id,
        models.HourlyAgg.campaign_id == campaign_id,
        models.HourlyAgg.date >= start_date,
        models.HourlyAgg.date <= end_date,
    )
    if age_group:
        hourly_query = hourly_query.filter(models.HourlyAgg.age_group == age_group)
    if gender:
        hourly_query = hourly_query.filter(models.HourlyAgg.gender == gender)

    hour_map = {h: {"exposure_count": 0, "interested_count": 0} for h in range(24)}
    for r in hourly_query.all():
        hour_map[r.hour]["exposure_count"]  += r.exposure_count
        hour_map[r.hour]["interested_count"] += r.interested_count

    hourly_trend = [{"hour": f"{h:02d}", **hour_map[h]} for h in range(24)]
    peak_hour    = max(hour_map, key=lambda h: hour_map[h]["exposure_count"]) if total_exposure > 0 else None

    # ── daily_trend ───────────────────────────────────────────────────────────
    date_map: dict[str, dict] = {}
    for r in daily_rows:
        d = str(r.date)
        if d not in date_map:
            date_map[d] = {"exposure_count": 0, "interested_count": 0}
        date_map[d]["exposure_count"]  += r.exposure_count
        date_map[d]["interested_count"] += r.interested_count

    daily_trend = [{"date": d, **date_map[d]} for d in sorted(date_map.keys())]

    return {
        "start_date":  str(start_date),
        "end_date":    str(end_date),
        "device_id":   str(device_id),
        "campaign_id": str(campaign_id),
        "exposure_count":          total_exposure,
        "avg_dwell_time_ms":       avg_dwell_time_ms,
        "interested_count":        total_interested,
        "attention_rate_tracks":   attention_rate_tracks,
        "total_attention_time_ms": float(total_attention),
        "attention_rate_times":    attention_rate_times,
        "count_10s":      count_10s,
        "count_20s":      count_20s,
        "count_30s":      count_30s,
        "count_40s":      count_40s,
        "count_50s_plus": count_50s_plus,
        "count_60s_plus": count_60s_plus,
        "count_male":     count_male,
        "count_female":   count_female,
        "avg_revisit_count":       avg_revisit_count,
        "avg_fixation_latency_ms": avg_fixation_latency_ms,
        "viewability_score":       viewability_score,
        "avg_attention_time_ms":   avg_attention_time_ms,
        "peak_hour":               peak_hour,
        "target_match_rate":       target_match_rate,
        "hourly_trend": hourly_trend,
        "daily_trend":  daily_trend,
    }