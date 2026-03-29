import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import EventRaw, DailyAgg, HourlyAgg

# 이 파일의 로거 생성 — 경고/정보 메시지를 터미널에 출력하는 데 사용
logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────────────────

# AI팀이 보내는 나이대 문자열을 DB 컬럼명으로 매핑하는 딕셔너리
# AI팀 형식: "10-19", "20-29", ... (segment.json 기준)
# DB 컬럼명: count_10s, count_20s, ...
AGE_MAP = {
    "10-19": "count_10s",
    "20-29": "count_20s",
    "30-39": "count_30s",
    "40-49": "count_40s",
    "50-59": "count_50s_plus",
}

# 배치 주기 (분)
# AI팀은 10분마다 데이터를 배치로 전송함
# ts(AI팀이 찍은 시각)와 ingested_at(서버 수신 시각)의 차이가
# 이 값보다 크면 네트워크 지연 또는 기기 장애를 의심할 수 있음
BATCH_INTERVAL_MINUTES = 10


# ── 내부 헬퍼 함수 ────────────────────────────────────────────────────────────

def _check_batch_delay(ts: datetime, ingested_at: datetime) -> None:
    """
    배치 지연을 감지하고 경고 로그를 출력합니다.

    AI팀 기기(노트북)는 NTP로 시간이 자동 동기화되므로 ts는 신뢰할 수 있습니다.
    따라서 ts와 ingested_at의 차이가 배치 주기(10분)보다 크다면
    네트워크 문제 또는 기기 장애가 발생했을 가능성이 있습니다.

    Args:
        ts: AI팀이 찍은 배치 기준 시각 (segment.timestamp)
        ingested_at: 서버가 요청을 수신한 시각 (server_default=func.now())
    """
    diff = ingested_at - ts
    if diff > timedelta(minutes=BATCH_INTERVAL_MINUTES):
        logger.warning(
            f"배치 지연 감지 | ts={ts} | ingested_at={ingested_at} | 지연={diff}"
        )


def _build_agg_counts(rows: list[EventRaw]) -> dict:
    """
    events_raw 행 목록을 받아 집계 지표를 계산하고 딕셔너리로 반환합니다.
    daily_agg와 hourly_agg 모두 동일한 집계 로직을 사용하므로 공통 함수로 분리했습니다.

    관심 인구 판단 기준:
        AI팀이 1500ms 이상인 look_time만 정제해서 보내기로 했으므로
        look_times 리스트가 비어있지 않으면 무조건 관심 인구로 판단합니다.

    Args:
        rows: 집계할 events_raw 행 목록 (같은 device_id, campaign_id, 날짜/시간 기준)

    Returns:
        dict: 집계 결과 딕셔너리
            - exposure_count     : 전체 노출 인구 수 (전체 행 수)
            - interested_count   : 관심 인구 수 (look_times가 있는 행 수)
            - attention_rate     : 관심도 = interested_count / exposure_count (소수점 4자리)
            - avg_viewing_time_ms: 관심 인구의 평균 시청 시간 (ms, 소수점 2자리)
            - count_10s ~ count_50s_plus: 나이대별 인원
            - count_male / count_female : 성별 인원
    """
    # 전체 노출 인구 = 전달받은 행 수
    exposure_count = len(rows)

    # 관심 인구 = look_times 리스트가 비어있지 않은 행
    # look_times가 빈 리스트([])이면 False, 원소가 하나라도 있으면 True
    interested_rows  = [r for r in rows if r.look_times]
    interested_count = len(interested_rows)

    # 관심도 = 관심 인구 / 전체 노출 인구
    # exposure_count가 0이면 ZeroDivisionError 방지를 위해 0.0 반환
    attention_rate = (
        round(interested_count / exposure_count, 4) if exposure_count > 0 else 0.0
    )

    # 평균 시청 시간 = 관심 인구의 total_look_duration_ms 합계 / 관심 인구 수
    # 관심 인구가 0이면 ZeroDivisionError 방지를 위해 0.0 반환
    avg_viewing_time_ms = (
        sum(r.total_look_duration_ms for r in interested_rows) / interested_count
        if interested_count > 0 else 0.0
    )

    # 나이대별 카운트 딕셔너리 초기화
    # AGE_MAP의 value(컬럼명)를 key로, 0을 value로 초기화
    # 예: {"count_10s": 0, "count_20s": 0, ...}
    age_counts = {col: 0 for col in AGE_MAP.values()}

    count_male   = 0
    count_female = 0

    for row in rows:
        # age_group이 null이거나 AGE_MAP에 없는 값이면 카운트하지 않음
        # (AI팀이 분석 못한 경우 age_group이 null로 올 수 있음)
        if row.age_group and row.age_group in AGE_MAP:
            age_counts[AGE_MAP[row.age_group]] += 1

        # 성별 카운트
        if row.gender == "male":
            count_male += 1
        elif row.gender == "female":
            count_female += 1

    # 모든 집계 결과를 하나의 딕셔너리로 반환
    # **age_counts로 나이대별 컬럼을 딕셔너리에 펼쳐 넣음
    return {
        "exposure_count":      exposure_count,
        "interested_count":    interested_count,
        "attention_rate":      attention_rate,
        "avg_viewing_time_ms": round(avg_viewing_time_ms, 2),
        **age_counts,
        "count_male":   count_male,
        "count_female": count_female,
    }


# ── 집계 실행 함수 ─────────────────────────────────────────────────────────────

def run_daily_aggregation(db: Session, target_date: date | None = None) -> None:
    """
    특정 날짜의 events_raw를 daily_aggs 테이블에 일 단위로 집계합니다.

    집계 기준:
        - ts 컬럼 (AI팀이 찍은 배치 기준 시각) 기준으로 날짜를 필터링
        - (device_id, campaign_id) 조합별로 그룹핑하여 각각 1행으로 저장
        - 이미 해당 날짜의 집계 데이터가 있으면 UPDATE, 없으면 INSERT

    Args:
        db: SQLAlchemy 세션
        target_date: 집계할 날짜. None이면 어제 날짜를 자동으로 사용.
                     APScheduler가 매일 자정에 target_date 없이 호출하므로
                     자동으로 전날 데이터를 집계합니다.
    """
    # target_date가 없으면 어제 날짜를 사용
    # (자정에 실행되므로 어제 = 방금 끝난 하루)
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    logger.info(f"[DailyAgg] 집계 시작 | date={target_date}")

    # ts 컬럼의 날짜 부분만 추출해서 target_date와 비교
    # func.date()는 PostgreSQL의 DATE() 함수로 DateTime → Date 변환
    rows = (
        db.query(EventRaw)
        .filter(func.date(EventRaw.ts) == target_date)
        .all()
    )

    # 데이터가 없으면 집계하지 않고 종료
    if not rows:
        logger.info(f"[DailyAgg] 데이터 없음 | date={target_date}")
        return

    # 각 행의 배치 지연 여부 확인 (ts와 ingested_at 차이 체크)
    for row in rows:
        _check_batch_delay(row.ts, row.ingested_at)

    # (device_id, campaign_id) 조합별로 행을 그룹핑
    # 같은 기기, 같은 캠페인의 데이터를 묶어서 집계
    # 예: {(device_uuid_1, campaign_uuid_1): [row1, row2, ...], ...}
    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
        key = (row.device_id, row.campaign_id)
        groups.setdefault(key, []).append(row)

    # 각 그룹별로 집계 후 DB에 저장
    for (device_id, campaign_id), group_rows in groups.items():
        counts = _build_agg_counts(group_rows)

        # 이미 같은 날짜/기기/캠페인 조합의 집계 데이터가 있는지 확인
        # (스케줄러가 실수로 두 번 실행되는 경우를 대비)
        existing = (
            db.query(DailyAgg)
            .filter_by(date=target_date, device_id=device_id, campaign_id=campaign_id)
            .first()
        )

        if existing:
            # 이미 있으면 각 컬럼 값을 업데이트
            for key, val in counts.items():
                setattr(existing, key, val)
            logger.info(f"[DailyAgg] 업데이트 | date={target_date} | device={device_id} | campaign={campaign_id}")
        else:
            # 없으면 새 행 INSERT
            # **counts로 딕셔너리를 키워드 인자로 펼쳐서 DailyAgg 객체 생성
            db.add(DailyAgg(
                date=target_date,
                device_id=device_id,
                campaign_id=campaign_id,
                **counts,
            ))
            logger.info(f"[DailyAgg] 신규 INSERT | date={target_date} | device={device_id} | campaign={campaign_id}")

    # 모든 그룹 처리 완료 후 한 번에 커밋
    db.commit()
    logger.info(f"[DailyAgg] 집계 완료 | date={target_date} | 그룹 수={len(groups)}")


def run_hourly_aggregation(db: Session, target_date: date | None = None) -> None:
    """
    특정 날짜의 events_raw를 hourly_aggs 테이블에 시간 단위로 집계합니다.

    집계 기준:
        - ts 컬럼 기준으로 날짜를 필터링
        - ts의 분/초를 버리고 시간 단위로 버킷화 (예: 14:35:22 → 14:00:00)
        - (device_id, campaign_id, hour) 조합별로 그룹핑하여 각각 1행으로 저장
        - 이미 해당 시간의 집계 데이터가 있으면 UPDATE, 없으면 INSERT

    Args:
        db: SQLAlchemy 세션
        target_date: 집계할 날짜. None이면 어제 날짜를 자동으로 사용.
    """
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    logger.info(f"[HourlyAgg] 집계 시작 | date={target_date}")

    rows = (
        db.query(EventRaw)
        .filter(func.date(EventRaw.ts) == target_date)
        .all()
    )

    if not rows:
        logger.info(f"[HourlyAgg] 데이터 없음 | date={target_date}")
        return

    # (device_id, campaign_id, hour_bucket) 조합별로 행을 그룹핑
    # hour_bucket: ts의 분/초/마이크로초를 0으로 만들어 시간 단위로 통일
    # 예: 2026-03-25 14:35:22+09:00 → 2026-03-25 14:00:00+09:00
    groups: dict[tuple, list[EventRaw]] = {}
    for row in rows:
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


def run_all_aggregations(db: Session, target_date: date | None = None) -> None:
    """
    daily + hourly 집계를 한 번에 실행합니다.

    APScheduler가 매일 자정에 이 함수를 호출합니다.
    테스트 시에는 직접 호출할 수 있습니다:

        from database import SessionLocal
        from Aggregation import run_all_aggregations
        from datetime import date

        db = SessionLocal()
        run_all_aggregations(db, target_date=date(2026, 3, 25))
        db.close()

    Args:
        db: SQLAlchemy 세션
        target_date: 집계할 날짜. None이면 어제 날짜를 자동으로 사용.
    """
    run_daily_aggregation(db, target_date)
    run_hourly_aggregation(db, target_date)