import models
from models import EventRaw
from datetime import timezone, timedelta

KST = timezone(timedelta(hours=9))

# ── 상수 ─────────────────────────────────────────────────────────────────────

AGE_MAP = {
    "10-19": "count_10s",
    "20-29": "count_20s",
    "30-39": "count_30s",
    "40-49": "count_40s",
    "50-59": "count_50s_plus",
    "60+":   "count_60s_plus",
}


def _build_agg_counts(rows: list[EventRaw]) -> dict:
    """기본 집계 지표 계산"""
    exposure_count    = len(rows)
    total_exposure_ms = sum(r.exposure_ms for r in rows)
    avg_dwell_time_ms = total_exposure_ms / exposure_count if exposure_count > 0 else 0.0

    interested_rows         = [r for r in rows if r.look_times]
    interested_count        = len(interested_rows)
    attention_rate_tracks   = round(interested_count / exposure_count, 4) if exposure_count > 0 else 0.0
    total_attention_time_ms = sum(r.total_look_duration_ms for r in interested_rows)
    attention_rate_times    = (
        round(total_attention_time_ms / total_exposure_ms, 4)
        if total_exposure_ms > 0 else 0.0
    )

    age_counts = {col: 0 for col in AGE_MAP.values()}
    count_male = count_female = 0

    for row in rows:
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


def _build_advanced_agg_counts(rows: list[EventRaw], campaign: models.Campaign) -> dict:
    """고급 분석 지표 계산"""
    exposure_count  = len(rows)
    interested_rows = [r for r in rows if r.look_times]

    # 반복 시선 횟수 수정: look_times 1개 이상인 track만 계산
    revisit_rows = [r for r in rows if len(r.look_times) > 1]
    avg_revisit_count = (
        round(sum(len(r.look_times) for r in revisit_rows) / len(revisit_rows), 4)
        if revisit_rows else 0.0
    )

    # 첫 주목 반응 시간 (roi_entry_ms 있는 경우만)
    fixation_latencies = []
    for r in interested_rows:
        if r.roi_entry_ms is not None and r.look_times:
            latency = r.look_times[0]["start_ms"] - r.roi_entry_ms
            if latency >= 0:
                fixation_latencies.append(latency)
    avg_fixation_latency_ms = (
        round(sum(fixation_latencies) / len(fixation_latencies), 2)
        if fixation_latencies else None
    )

    # 노출 대비 시청 효율
    attention_rate_tracks = (
        round(len(interested_rows) / exposure_count, 4) if exposure_count > 0 else 0.0
    )
    avg_look_duration_ms = (
        sum(r.total_look_duration_ms for r in interested_rows) / len(interested_rows)
        if interested_rows else 0.0
    )
    viewability_score = round(attention_rate_tracks * avg_look_duration_ms, 4)

    # 평균 광고 시청 시간 추가 (관심 인구만)
    avg_attention_time_ms = round(avg_look_duration_ms, 2)

    # 피크 시간
    hour_counts: dict[int, int] = {}
    for r in rows:
        h = r.ts.astimezone(KST).hour
        hour_counts[h] = hour_counts.get(h, 0) + 1
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    # 타겟 오디언스 정합률
    target_match_rate = None
    if interested_rows and (campaign.target_age_group or campaign.target_gender):
        matched = sum(
            1 for r in interested_rows
            if (campaign.target_age_group is None or r.age_group == campaign.target_age_group)
            and (campaign.target_gender    is None or r.gender    == campaign.target_gender)
        )
        target_match_rate = round(matched / len(interested_rows), 4)

    return {
        "avg_revisit_count":       avg_revisit_count,
        "avg_fixation_latency_ms": avg_fixation_latency_ms,
        "viewability_score":       viewability_score,
        "avg_attention_time_ms":   avg_attention_time_ms,
        "peak_hour":               peak_hour,
        "target_match_rate":       target_match_rate,
    }