import uuid

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
import models, schemas
from aggregation_helpers import _build_agg_counts, _build_advanced_agg_counts
from analysis.golden_zone import run_golden_zone

router = APIRouter()

KST = timezone(timedelta(hours=9))


# # ── GET /stats/daily/ ─────────────────────────────────────────────────────────

# @router.get(
#     "/daily/",
#     response_model=schemas.DailyAggListResponse,
#     summary="일별 집계 조회",
# )
# def get_daily_aggs(
#     device_id:   Optional[uuid.UUID] = None,
#     campaign_id: Optional[uuid.UUID] = None,
#     start_date:  Optional[date]      = None,
#     end_date:    Optional[date]      = None,
#     target_date: Optional[date]      = None,  # 특정 날짜
#     limit:       int = Query(default=100, ge=1, le=1000),
#     db: Session = Depends(get_db),
# ):
#     query = db.query(models.DailyAgg)

#     if device_id:
#         query = query.filter(models.DailyAgg.device_id == device_id)
#     if campaign_id:
#         query = query.filter(models.DailyAgg.campaign_id == campaign_id)
#     if target_date:
#         query = query.filter(models.DailyAgg.date == target_date)
#     else:
#         if start_date:
#             query = query.filter(models.DailyAgg.date >= start_date)
#         if end_date:
#             query = query.filter(models.DailyAgg.date <= end_date)

#     rows = query.order_by(models.DailyAgg.date.desc()).limit(limit).all()
#     return schemas.DailyAggListResponse(results=rows, total=len(rows))


# # ── GET /stats/hourly/ ────────────────────────────────────────────────────────

# @router.get(
#     "/hourly/",
#     response_model=schemas.HourlyAggListResponse,
#     summary="시간별 집계 조회",
# )
# def get_hourly_aggs(
#     device_id:   Optional[uuid.UUID] = None,
#     campaign_id: Optional[uuid.UUID] = None,
#     start_date:  Optional[date]      = None,
#     end_date:    Optional[date]      = None,
#     target_date: Optional[date]      = None,
#     limit:       int = Query(default=100, ge=1, le=1000),
#     db: Session = Depends(get_db),
# ):
#     query = db.query(models.HourlyAgg)

#     if device_id:
#         query = query.filter(models.HourlyAgg.device_id == device_id)
#     if campaign_id:
#         query = query.filter(models.HourlyAgg.campaign_id == campaign_id)
#     if target_date:
#         query = query.filter(
#             models.HourlyAgg.hour >= target_date,
#             models.HourlyAgg.hour  < target_date + timedelta(days=1),
#         )
#     else:
#         if start_date:
#             query = query.filter(models.HourlyAgg.hour >= start_date)
#         if end_date:
#             query = query.filter(models.HourlyAgg.hour  < end_date + timedelta(days=1))

#     rows = query.order_by(models.HourlyAgg.hour.desc()).limit(limit).all()
#     return schemas.HourlyAggListResponse(results=rows, total=len(rows))


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
    summary="기간별 집계 조회 (실시간 계산)",
    description="기본 지표 + 고급 지표 + hourly/daily 추이를 한 번에 반환합니다.",
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
    # 날짜 유효성 확인
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date는 end_date보다 클 수 없습니다.")

    # device_id + campaign_id 조합 유효성 확인
    device_campaign = (
        db.query(models.DeviceCampaign)
        .filter_by(device_id=device_id, campaign_id=campaign_id)
        .first()
    )
    if not device_campaign:
        raise HTTPException(status_code=404, detail="등록되지 않은 device-campaign 조합입니다.")

    campaign = db.query(models.Campaign).filter_by(id=campaign_id).first()

    # 3번 수정: KST→UTC 변환 후 범위 비교 (인덱스 사용 가능)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=KST)
    end_dt   = datetime(end_date.year,   end_date.month,   end_date.day,   tzinfo=KST) + timedelta(days=1)

    query = (
        db.query(models.EventRaw)
        .filter(
            models.EventRaw.device_id   == device_id,
            models.EventRaw.campaign_id == campaign_id,
            models.EventRaw.ts >= start_dt,
            models.EventRaw.ts <  end_dt,
        )
    )

    if age_group:
        query = query.filter(models.EventRaw.age_group == age_group)
    if gender:
        query = query.filter(models.EventRaw.gender == gender)

    rows = query.all()

    # 데이터 없어도 200 반환
    empty_summary = {
        "exposure_count": 0, "avg_dwell_time_ms": 0.0, "interested_count": 0,
        "attention_rate_tracks": 0.0, "total_attention_time_ms": 0.0,
        "attention_rate_times": 0.0, "count_10s": 0, "count_20s": 0,
        "count_30s": 0, "count_40s": 0, "count_50s_plus": 0,
        "count_60s_plus": 0, "count_male": 0, "count_female": 0,
    }
    empty_advanced = {
        "avg_revisit_count":       0.0,
        "avg_fixation_latency_ms": None,
        "viewability_score":       0.0,
        "reactance_rate":          0.0,
        "peak_hour":               None,
        "target_match_rate":       None,
    }

    summary  = _build_agg_counts(rows)                    if rows else empty_summary
    advanced = _build_advanced_agg_counts(rows, campaign) if rows else empty_advanced

    # hourly_trend — 00~23시 24개 고정 (KST 기준)
    hour_map: dict[int, dict] = {h: {"exposure_count": 0, "interested_count": 0} for h in range(24)}
    for row in rows:
        kst_hour = row.ts.astimezone(KST).hour
        hour_map[kst_hour]["exposure_count"]  += 1
        hour_map[kst_hour]["interested_count"] += 1 if row.look_times else 0

    hourly_trend = [
        {"hour": f"{h:02d}", **hour_map[h]}
        for h in range(24)
    ]

    # daily_trend — 데이터 있는 날짜만, 오름차순
    date_map: dict[str, dict] = {}
    for row in rows:
        kst_date = str(row.ts.astimezone(KST).date())
        if kst_date not in date_map:
            date_map[kst_date] = {"exposure_count": 0, "interested_count": 0}
        date_map[kst_date]["exposure_count"]  += 1
        date_map[kst_date]["interested_count"] += 1 if row.look_times else 0

    daily_trend = [
        {"date": d, **date_map[d]}
        for d in sorted(date_map.keys())
    ]

    return {
        "start_date":  str(start_date),
        "end_date":    str(end_date),
        "device_id":   str(device_id),
        "campaign_id": str(campaign_id),
        **summary,
        **advanced,
        "hourly_trend": hourly_trend,
        "daily_trend":  daily_trend,
    }