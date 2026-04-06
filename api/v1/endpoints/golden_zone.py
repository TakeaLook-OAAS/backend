import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models

router = APIRouter()


@router.get(
    "/",
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
    return {
        "campaign_id":  str(campaign_id),
        "device_id":    str(device_id),
        "computed_at":  first.computed_at,
        "point_count":  first.point_count,
        "event_count":  first.event_count,
        "dbscan": {
            "eps":           first.eps,
            "min_samples":   first.min_samples,
            "cluster_count": first.cluster_count,
            "noise_count":   first.noise_count,
        },
        "clusters": [
            {
                "label":       row.cluster_label,
                "point_count": row.cluster_point_count,
                "is_main":     row.is_main,
                "convex_hull": row.convex_hull,
                "ellipse":     row.ellipse,
            }
            for row in agg_rows
        ],
    }
