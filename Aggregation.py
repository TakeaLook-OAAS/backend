# # ts 기준으로 어제 날짜 데이터만 조회
# events_raw에서 DATE(ts) = 어제
# ```

# ---

# **어떻게 그룹핑하나요?**
# ```
# 같은 기기 + 같은 캠페인끼리 묶음

# 예시:
# 기기A + 삼성광고 → 50명 데이터 → 집계 1행
# 기기A + 나이키광고 → 30명 데이터 → 집계 1행
# ```

# ---

# **각 그룹에서 뭘 계산하나요?**

# | 지표 | 계산식 |
# |------|--------|
# | 노출 인구 | 전체 track 수 |
# | Avg Dwell Time | sum(exposure_ms) / 전체 track 수 |
# | Attention Time | sum(total_look_duration_ms) — 관심 인구만 |
# | Attention Rate_Tracks | 관심 인구 / 전체 인구 |
# | Attention Rate_Times | Attention Time / sum(exposure_ms) |
# | 나이대/성별 | 각각 카운트 |

# ---

# **세 가지 집계를 실행해요**
# ```
# run_daily_aggregation()   → daily_aggs (날짜별)
# run_hourly_aggregation()  → hourly_aggs (시간별)
# run_campaign_aggregation()→ campaign_aggs (캠페인 전체 기간)

import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import EventRaw, DailyAgg, HourlyAgg, CampaignAgg
from analysis.golden_zone import run_golden_zone, save_golden_zone

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────────────────

# AI팀이 보내는 나이대 문자열을 DB 컬럼명으로 매핑
AGE_MAP = {
    "10-19": "count_10s",
    "20-29": "count_20s",
    "30-39": "count_30s",
    "40-49": "count_40s",
    "50-59": "count_50s_plus",
    "60+":   "count_60s_plus",
}

# 배치 주기 (분) — ts와 ingested_at 차이가 이 값보다 크면 경고
BATCH_INTERVAL_MINUTES = 10

# !!! 테스트를 위해 배치 지연 로직을 잠시 주석처리함 !!!
# # ── 내부 헬퍼 함수 ────────────────────────────────────────────────────────────

# def _check_batch_delay(ts: datetime, ingested_at: datetime) -> None:
#     """
#     ts와 ingested_at 차이가 배치 주기(10분)보다 크면 경고 로그 출력.
#     AI팀 기기는 NTP로 시간 동기화되므로 ts는 신뢰할 수 있음.
#     """
#     diff = ingested_at - ts
#     if diff > timedelta(minutes=BATCH_INTERVAL_MINUTES):
#         logger.warning(
#             f"배치 지연 감지 | ts={ts} | ingested_at={ingested_at} | 지연={diff}"
#         )


def _build_agg_counts(rows: list[EventRaw]) -> dict:
    """
    events_raw 행 목록을 받아 집계 지표를 계산하고 딕셔너리로 반환합니다.

    지표 계산 방식:
        - exposure_count        : 전체 Track 수
        - avg_dwell_time_ms     : sum(exposure_ms) / 전체 Track 수
        - interested_count      : look_times가 있는 Track 수
        - attention_rate_tracks : interested_count / exposure_count
        - total_attention_time_ms: sum(total_look_duration_ms) — 관심 인구만
        - attention_rate_times  : total_attention_time_ms / sum(exposure_ms)
        - count_10s ~ count_60s_plus: 나이대별 인원
        - count_male / count_female : 성별 인원
    """
    # ── 노출 인구 ──────────────────────────────────────────────────────────────
    exposure_count = len(rows)

    # ── 체류 시간 ─────────────────────────────────────────────────────────────
    # 전체 Track의 exposure_ms 합계
    total_exposure_ms = sum(r.exposure_ms for r in rows)

    # Avg Dwell Time = 총 체류시간 / 전체 Track 수
    avg_dwell_time_ms = (
        total_exposure_ms / exposure_count if exposure_count > 0 else 0.0
    )

    # ── 관심 인구 ─────────────────────────────────────────────────────────────
    # look_times가 비어있지 않은 Track = 관심 인구
    interested_rows  = [r for r in rows if r.look_times]
    interested_count = len(interested_rows)

    # Attention Rate_Tracks = 관심 인구 / 전체 인구
    attention_rate_tracks = (
        round(interested_count / exposure_count, 4) if exposure_count > 0 else 0.0
    )

    # ── 시청 시간 ─────────────────────────────────────────────────────────────
    # Attention Time = 관심 인구의 total_look_duration_ms 합계
    total_attention_time_ms = sum(r.total_look_duration_ms for r in interested_rows)

    # Attention Rate_Times = Attention Time / 전체 인구의 exposure_ms 합계
    attention_rate_times = (
        round(total_attention_time_ms / total_exposure_ms, 4)
        if total_exposure_ms > 0 else 0.0
    )

    # ── 나이대 / 성별 카운트 ─────────────────────────────────────────────────
    age_counts = {col: 0 for col in AGE_MAP.values()}
    count_male   = 0
    count_female = 0

    for row in rows:
        # age_group이 null이거나 AGE_MAP에 없는 값이면 카운트하지 않음
        if row.age_group and row.age_group in AGE_MAP:
            age_counts[AGE_MAP[row.age_group]] += 1

        if row.gender == "male":
            count_male += 1
        elif row.gender == "female":
            count_female += 1

    return {
        "exposure_count":          exposure_count,
        "avg_dwell_time_ms":       round(avg_dwell_time_ms, 2),
        "interested_count":        interested_count,
        "attention_rate_tracks":   attention_rate_tracks,
        "total_attention_time_ms": float(total_attention_time_ms),
        "attention_rate_times":    attention_rate_times,
        **age_counts,
        "count_male":   count_male,
        "count_female": count_female,
    }


# ── 집계 실행 함수 ─────────────────────────────────────────────────────────────

def run_daily_aggregation(db: Session, target_date: date | None = None) -> None:
    """
    특정 날짜의 events_raw를 daily_aggs에 일 단위로 집계합니다.
    target_date가 None이면 어제 날짜를 자동으로 사용합니다.
    """
    if target_date is None:
        target_date = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)).date()

    logger.info(f"[DailyAgg] 집계 시작 | date={target_date}")

    rows = (
        db.query(EventRaw)
        .filter(func.date(func.timezone('Asia/Seoul', EventRaw.ts)) == target_date)
        .all()
    )

    if not rows:
        logger.info(f"[DailyAgg] 데이터 없음 | date={target_date}")
        return

    # for row in rows:
    #     _check_batch_delay(row.ts, row.ingested_at)

    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        key = (row.device_id, row.campaign_id)
        groups.setdefault(key, []).append(row)

    for (device_id, campaign_id), group_rows in groups.items():
        counts = _build_agg_counts(group_rows)

        existing = (
            db.query(DailyAgg)
            .filter_by(date=target_date, device_id=device_id, campaign_id=campaign_id)
            .first()
        )

        if existing:
            for key, val in counts.items():
                setattr(existing, key, val)
            logger.info(f"[DailyAgg] 업데이트 | date={target_date} | device={device_id} | campaign={campaign_id}")
        else:
            db.add(DailyAgg(
                date=target_date,
                device_id=device_id,
                campaign_id=campaign_id,
                **counts,
            ))
            logger.info(f"[DailyAgg] 신규 INSERT | date={target_date} | device={device_id} | campaign={campaign_id}")

    db.commit()
    logger.info(f"[DailyAgg] 집계 완료 | date={target_date} | 그룹 수={len(groups)}")


def run_hourly_aggregation(db: Session, target_date: date | None = None) -> None:
    """
    특정 날짜의 events_raw를 hourly_aggs에 시간 단위로 집계합니다.
    target_date가 None이면 어제 날짜를 자동으로 사용합니다.
    """
    if target_date is None:
        target_date = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)).date()

    logger.info(f"[HourlyAgg] 집계 시작 | date={target_date}")

    rows = (
        db.query(EventRaw)
        .filter(func.date(func.timezone('Asia/Seoul', EventRaw.ts)) == target_date)
        .all()
    )

    if not rows:
        logger.info(f"[HourlyAgg] 데이터 없음 | date={target_date}")
        return

    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        # ts의 분/초를 버리고 시간 단위 버킷화 (14:35 → 14:00), KST 기준
        hour_bucket = row.ts.replace(minute=0, second=0, microsecond=0)
        key = (row.device_id, row.campaign_id, hour_bucket)
        groups.setdefault(key, []).append(row)

    for (device_id, campaign_id, hour_bucket), group_rows in groups.items():
        counts = _build_agg_counts(group_rows)

        existing = (
            db.query(HourlyAgg)
            .filter_by(hour=hour_bucket, device_id=device_id, campaign_id=campaign_id)
            .first()
        )

        if existing:
            for key, val in counts.items():
                setattr(existing, key, val)
            logger.info(f"[HourlyAgg] 업데이트 | hour={hour_bucket} | device={device_id} | campaign={campaign_id}")
        else:
            db.add(HourlyAgg(
                hour=hour_bucket,
                device_id=device_id,
                campaign_id=campaign_id,
                **counts,
            ))
            logger.info(f"[HourlyAgg] 신규 INSERT | hour={hour_bucket} | device={device_id} | campaign={campaign_id}")

    db.commit()
    logger.info(f"[HourlyAgg] 집계 완료 | date={target_date} | 그룹 수={len(groups)}")


def run_campaign_aggregation(db: Session, campaign_id=None) -> None:
    """
    캠페인 전체 기간의 events_raw를 campaign_aggs에 집계합니다.
    campaign_id가 None이면 전체 캠페인 대상으로 집계합니다.
    """
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
        key = (row.device_id, row.campaign_id)
        groups.setdefault(key, []).append(row)

    for (device_id, camp_id), group_rows in groups.items():
        counts = _build_agg_counts(group_rows)

        existing = (
            db.query(CampaignAgg)
            .filter_by(device_id=device_id, campaign_id=camp_id)
            .first()
        )

        if existing:
            for key, val in counts.items():
                setattr(existing, key, val)
            logger.info(f"[CampaignAgg] 업데이트 | device={device_id} | campaign={camp_id}")
        else:
            db.add(CampaignAgg(
                device_id=device_id,
                campaign_id=camp_id,
                **counts,
            ))
            logger.info(f"[CampaignAgg] 신규 INSERT | device={device_id} | campaign={camp_id}")

    db.commit()
    logger.info(f"[CampaignAgg] 집계 완료 | 그룹 수={len(groups)}")


def run_dbscan_aggregation(db: Session) -> None:
    """
    모든 활성 기기×캠페인 조합에 대해 DBSCAN 골든존 분석을 실행하고
    결과를 dbscan_aggs에 저장합니다.
    look_times가 있는 전체 기간 데이터를 대상으로 계산합니다.
    """
    logger.info("[DbscanAgg] 집계 시작")

    # look_times가 있는 (device_id, campaign_id) 조합 전체 조회
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
        rows = (
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
                result      = result,
                campaign_id = campaign_id,
                device_id   = device_id,
                eps         = 100.0,
                min_samples = 10,
                n_interp    = 5,
                db          = db,
            )
            logger.info(
                f"[DbscanAgg] 저장 완료 | device={device_id} | campaign={campaign_id} "
                f"| 클러스터={result['dbscan']['cluster_count']}"
            )
        else:
            logger.info(
                f"[DbscanAgg] 건너뜀 ({result['status']}) "
                f"| device={device_id} | campaign={campaign_id}"
            )

    logger.info(f"[DbscanAgg] 집계 완료 | 처리한 조합={len(pairs)}")


def run_all_aggregations(db: Session, target_date: date | None = None) -> None:
    # noqa: E501 — 아래 docstring의 실행 예시는 python -m Aggregation 으로도 가능
    """
    daily + hourly + campaign 집계를 한 번에 실행합니다.
    APScheduler가 매일 자정에 이 함수를 호출합니다.

    직접 실행 예시:
        from database import SessionLocal
        from Aggregation import run_all_aggregations
        from datetime import date

        db = SessionLocal()
        run_all_aggregations(db, target_date=date(2026, 4, 3))
        db.close()
    """
    run_daily_aggregation(db, target_date)
    run_hourly_aggregation(db, target_date)
    run_campaign_aggregation(db)
    run_dbscan_aggregation(db)


if __name__ == "__main__":
    import sys
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 인자로 날짜 지정 가능: python -m Aggregation 2026-04-05
    # 인자 없으면 어제 날짜 자동 사용
    target: date | None = None
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
            print(f"집계 대상 날짜: {target}")
        except ValueError:
            print(f"날짜 형식 오류: {sys.argv[1]} (예: 2026-04-05)")
            sys.exit(1)
    else:
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        target = (datetime.now(KST) - timedelta(days=1)).date()
        print(f"날짜 미지정 → 어제 날짜 사용 (KST): {target}")

    from database import SessionLocal
    db = SessionLocal()
    try:
        run_all_aggregations(db, target_date=target)
        print("집계 완료")
    finally:
        db.close()