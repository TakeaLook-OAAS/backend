import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import EventRaw, CampaignAgg, DailyAgg, HourlyAgg
from Aggregation.golden_zone import run_golden_zone, save_golden_zone
from Aggregation.aggregation_helpers import _build_agg_counts, _build_advanced_agg_counts
import database.models as models

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def _null_safe_filter(col, val):
    """NULL 안전 필터 — val이 None이면 IS NULL, 아니면 = val"""
    return col.is_(None) if val is None else col == val


def run_daily_aggregation(
    db: Session,
    target_date: date,
    campaign_id=None,
    device_id=None,
) -> None:
    """일별 사전 집계 → daily_aggs + hourly_aggs"""
    logger.info(f"[DailyAgg] 집계 시작 | date={target_date} | campaign_id={campaign_id}")

    start_dt = datetime(target_date.year, target_date.month, target_date.day, tzinfo=KST)
    end_dt   = start_dt + timedelta(days=1)

    query = db.query(EventRaw).filter(
        EventRaw.ts >= start_dt,
        EventRaw.ts <  end_dt,
    )
    if campaign_id is not None:
        query = query.filter(EventRaw.campaign_id == campaign_id)
    if device_id is not None:
        query = query.filter(EventRaw.device_id == device_id)

    rows = query.all()
    if not rows:
        logger.info(f"[DailyAgg] 데이터 없음 | date={target_date}")
        return

    # campaign 일괄 조회 (N+1 방지)
    camp_ids  = {r.campaign_id for r in rows}
    campaigns = {
        c.id: c for c in
        db.query(models.Campaign).filter(models.Campaign.id.in_(camp_ids)).all()
    }

    # ── DailyAgg ─────────────────────────────────────────────────────────────
    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        key = (row.device_id, row.campaign_id, row.age_group, row.gender)
        groups.setdefault(key, []).append(row)

    for (dev_id, camp_id, age_grp, gender), group_rows in groups.items():
        campaign = campaigns.get(camp_id)
        if not campaign:
            continue

        interested_rows = [r for r in group_rows if r.look_times]
        revisit_rows    = [r for r in group_rows if len(r.look_times) > 1]

        # fixation latency
        fixation_latencies = [
            r.look_times[0]["start_ms"] - r.roi_entry_ms
            for r in interested_rows
            if r.roi_entry_ms is not None and r.look_times
            and r.look_times[0]["start_ms"] - r.roi_entry_ms >= 0
        ]

        # target match
        target_matched_count = None
        if interested_rows and (campaign.target_age_group or campaign.target_gender):
            target_matched_count = sum(
                1 for r in interested_rows
                if (campaign.target_age_group is None or r.age_group == campaign.target_age_group)
                and (campaign.target_gender    is None or r.gender    == campaign.target_gender)
            )

        values = dict(
            exposure_count            = len(group_rows),
            interested_count          = len(interested_rows),
            total_dwell_ms      = sum(r.exposure_ms or 0 for r in group_rows),
            total_attention_ms  = sum(r.total_look_duration_ms or 0 for r in interested_rows),
            revisit_track_count       = len(revisit_rows),
            total_revisit_look_count  = sum(len(r.look_times) for r in revisit_rows),
            total_fixation_latency_ms = float(sum(fixation_latencies)) if fixation_latencies else None,
            fixation_latency_count    = len(fixation_latencies),
            target_matched_count      = target_matched_count,
        )

        existing = db.query(DailyAgg).filter(
            DailyAgg.date        == target_date,
            DailyAgg.device_id   == dev_id,
            DailyAgg.campaign_id == camp_id,
            _null_safe_filter(DailyAgg.age_group, age_grp),
            _null_safe_filter(DailyAgg.gender,    gender),
        ).first()

        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
        else:
            db.add(DailyAgg(
                date=target_date, device_id=dev_id, campaign_id=camp_id,
                age_group=age_grp, gender=gender, **values,
            ))

    # ── HourlyAgg ────────────────────────────────────────────────────────────
    hourly_groups: dict[tuple, dict] = {}
    for row in rows:
        h   = row.ts.astimezone(KST).hour
        key = (row.device_id, row.campaign_id, row.age_group, row.gender, h)
        if key not in hourly_groups:
            hourly_groups[key] = {"exposure_count": 0, "interested_count": 0}
        hourly_groups[key]["exposure_count"]  += 1
        hourly_groups[key]["interested_count"] += 1 if row.look_times else 0

    for (dev_id, camp_id, age_grp, gender, hour), counts in hourly_groups.items():
        existing = db.query(HourlyAgg).filter(
            HourlyAgg.date        == target_date,
            HourlyAgg.hour        == hour,
            HourlyAgg.device_id   == dev_id,
            HourlyAgg.campaign_id == camp_id,
            _null_safe_filter(HourlyAgg.age_group, age_grp),
            _null_safe_filter(HourlyAgg.gender,    gender),
        ).first()

        if existing:
            existing.exposure_count   = counts["exposure_count"]
            existing.interested_count = counts["interested_count"]
        else:
            db.add(HourlyAgg(
                date=target_date, hour=hour,
                device_id=dev_id, campaign_id=camp_id,
                age_group=age_grp, gender=gender,
                **counts,
            ))

    db.commit()
    logger.info(f"[DailyAgg] 집계 완료 | date={target_date} | 그룹 수={len(groups)}")


def run_campaign_aggregation(db: Session, campaign_id=None) -> None:
    """캠페인 전체 기간 기본 + 고급 집계 → campaign_aggs"""
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

    for (dev_id, camp_id), group_rows in groups.items():
        campaign = db.query(models.Campaign).filter_by(id=camp_id).first()
        if not campaign:
            continue

        all_counts = {
            **_build_agg_counts(group_rows),
            **_build_advanced_agg_counts(group_rows, campaign),
        }

        existing = db.query(CampaignAgg).filter_by(device_id=dev_id, campaign_id=camp_id).first()
        if existing:
            for k, v in all_counts.items():
                setattr(existing, k, v)
            logger.info(f"[CampaignAgg] 업데이트 | device={dev_id} | campaign={camp_id}")
        else:
            db.add(CampaignAgg(device_id=dev_id, campaign_id=camp_id, **all_counts))
            logger.info(f"[CampaignAgg] 신규 INSERT | device={dev_id} | campaign={camp_id}")

    db.commit()
    logger.info(f"[CampaignAgg] 집계 완료 | 그룹 수={len(groups)}")


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

    for dev_id, camp_id in pairs:
        rows = (
            db.query(EventRaw)
            .filter(
                EventRaw.device_id   == dev_id,
                EventRaw.campaign_id == camp_id,
                func.jsonb_array_length(EventRaw.look_times) > 0,
            )
            .all()
        )
        result = run_golden_zone(rows=rows, eps=100.0, min_samples=10, n_interp=5)

        if result["status"] == "ok":
            save_golden_zone(
                result=result, campaign_id=camp_id, device_id=dev_id,
                eps=100.0, min_samples=10, n_interp=5, db=db,
            )
            logger.info(f"[DbscanAgg] 저장 완료 | device={dev_id} | campaign={camp_id}")
        else:
            logger.info(f"[DbscanAgg] 건너뜀 ({result['status']}) | device={dev_id} | campaign={camp_id}")

    logger.info(f"[DbscanAgg] 집계 완료 | 처리한 조합={len(pairs)}")


def run_all_aggregations(db: Session, target_date: date | None = None) -> None:
    if target_date is None:
        target_date = (datetime.now(KST) - timedelta(days=1)).date()
    run_daily_aggregation(db, target_date)
    run_campaign_aggregation(db)
    run_dbscan_aggregation(db)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

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

    from database.database import SessionLocal
    db = SessionLocal()
    try:
        run_all_aggregations(db, target)
        print("집계 완료")
    finally:
        db.close()