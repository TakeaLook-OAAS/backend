import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import EventRaw, CampaignAgg, CampaignAdvancedAgg
from analysis.golden_zone import run_golden_zone, save_golden_zone
from aggregation_helpers import _build_agg_counts, _build_advanced_agg_counts
import models

logger = logging.getLogger(__name__)


# ── 비활성화: 일/시간 단위 집계 (실시간 ROI 통계 기능으로 대체 예정) ──────────

# def run_daily_aggregation(db: Session, target_date: date | None = None) -> None:
#     ...

# def run_hourly_aggregation(db: Session, target_date: date | None = None) -> None:
#     ...


def run_campaign_aggregation(db: Session, campaign_id=None) -> None:
    """캠페인 전체 기간 기본 집계 → campaign_aggs"""
    logger.info(f"[CampaignAgg] 집계 시작 | campaign_id={campaign_id}")

    query = db.query(EventRaw)
    if campaign_id is not None:
        query = query.filter(EventRaw.campaign_id == campaign_id)
    rows = query.all()

    if not rows:
        logger.info(f"[CampaignAgg] 데이터 없음 | campaign_id={campaign_id}")
        return

    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        groups.setdefault((row.device_id, row.campaign_id), []).append(row)

    for (device_id, camp_id), group_rows in groups.items():
        counts   = _build_agg_counts(group_rows)
        existing = db.query(CampaignAgg).filter_by(device_id=device_id, campaign_id=camp_id).first()

        if existing:
            for k, v in counts.items():
                setattr(existing, k, v)
            logger.info(f"[CampaignAgg] 업데이트 | device={device_id} | campaign={camp_id}")
        else:
            db.add(CampaignAgg(device_id=device_id, campaign_id=camp_id, **counts))
            logger.info(f"[CampaignAgg] 신규 INSERT | device={device_id} | campaign={camp_id}")

    db.commit()
    logger.info(f"[CampaignAgg] 집계 완료 | 그룹 수={len(groups)}")


def run_advanced_aggregation(db: Session, campaign_id=None) -> None:
    """캠페인 전체 기간 고급 집계 → campaign_advanced_aggs"""
    logger.info(f"[AdvancedAgg] 집계 시작 | campaign_id={campaign_id}")

    query = db.query(EventRaw)
    if campaign_id is not None:
        query = query.filter(EventRaw.campaign_id == campaign_id)
    rows = query.all()

    if not rows:
        logger.info(f"[AdvancedAgg] 데이터 없음 | campaign_id={campaign_id}")
        return

    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        groups.setdefault((row.device_id, row.campaign_id), []).append(row)

    for (device_id, camp_id), group_rows in groups.items():
        campaign = db.query(models.Campaign).filter_by(id=camp_id).first()
        if not campaign:
            continue

        counts   = _build_advanced_agg_counts(group_rows, campaign)
        existing = db.query(CampaignAdvancedAgg).filter_by(device_id=device_id, campaign_id=camp_id).first()

        if existing:
            for k, v in counts.items():
                setattr(existing, k, v)
            logger.info(f"[AdvancedAgg] 업데이트 | device={device_id} | campaign={camp_id}")
        else:
            db.add(CampaignAdvancedAgg(device_id=device_id, campaign_id=camp_id, **counts))
            logger.info(f"[AdvancedAgg] 신규 INSERT | device={device_id} | campaign={camp_id}")

    db.commit()
    logger.info(f"[AdvancedAgg] 집계 완료 | 그룹 수={len(groups)}")


def run_dbscan_aggregation(db: Session) -> None:
    """골든존 DBSCAN 분석 → dbscan_aggs"""
    logger.info("[DbscanAgg] 집계 시작")

    pairs = (
        db.query(EventRaw.device_id, EventRaw.campaign_id)
        .filter(func.jsonb_array_length(EventRaw.look_times) > 0)
        .distinct()
        .all()
    )

    if not pairs:
        logger.info("[DbscanAgg] look_times 데이터 없음 — 건너뜀")
        return

    for device_id, campaign_id in pairs:
        rows   = (
            db.query(EventRaw)
            .filter(
                EventRaw.device_id   == device_id,
                EventRaw.campaign_id == campaign_id,
                func.jsonb_array_length(EventRaw.look_times) > 0,
            )
            .all()
        )
        result = run_golden_zone(rows=rows, eps=100.0, min_samples=10, n_interp=5)

        if result["status"] == "ok":
            save_golden_zone(
                result=result, campaign_id=campaign_id, device_id=device_id,
                eps=100.0, min_samples=10, n_interp=5, db=db,
            )
            logger.info(f"[DbscanAgg] 저장 완료 | device={device_id} | campaign={campaign_id} | 클러스터={result['dbscan']['cluster_count']}")
        else:
            logger.info(f"[DbscanAgg] 건너뜀 ({result['status']}) | device={device_id} | campaign={campaign_id}")

    logger.info(f"[DbscanAgg] 집계 완료 | 처리한 조합={len(pairs)}")


def run_all_aggregations(db: Session, target_date: date | None = None) -> None:
    """campaign + advanced + dbscan 집계를 한 번에 실행합니다."""
    run_campaign_aggregation(db)
    run_advanced_aggregation(db)
    run_dbscan_aggregation(db)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    KST    = timezone(timedelta(hours=9))
    target = (datetime.now(KST) - timedelta(days=1)).date()

    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
            print(f"집계 대상 날짜: {target}")
        except ValueError:
            print(f"날짜 형식 오류: {sys.argv[1]} (예: 2026-04-05)")
            sys.exit(1)
    else:
        print(f"날짜 미지정 → 어제 날짜 사용 (KST): {target}")

    from database import SessionLocal
    db = SessionLocal()
    try:
        run_all_aggregations(db)
        print("집계 완료")
    finally:
        db.close()