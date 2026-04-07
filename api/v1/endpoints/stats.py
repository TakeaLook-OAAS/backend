import uuid

from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, timedelta
from database import get_db
import models, schemas

router = APIRouter()


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

# --- DBSCAN ──────────────────────────────────────────────────────

@router.get(
    "/golden-zone/",
    response_model=schemas.GoldenZoneResponse,
    summary="골든존 조회",
    description=(
        "dbscan_aggs에 저장된 클러스터 결과를 반환합니다. "
        "매일 자정 run_all_aggregations()가 자동으로 갱신합니다."
    ),
)
def get_golden_zone(
    campaign_id: uuid.UUID,
    device_id:   uuid.UUID,
    db: Session = Depends(get_db),
):
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
            schemas.GoldenZoneCluster(
                label       = row.cluster_label,
                point_count = row.cluster_point_count,
                points      = row.points,
            )
            for row in agg_rows
        ],
    )
