"""
Aggregation._build_agg_counts() 단위 테스트

DB 없이 순수 Python 로직만 검증.
AI팀 샘플 JSON을 기반으로 집계 수치가 올바른지 확인.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from models import EventRaw
from Aggregation.Aggregation import _build_agg_counts


def row(
    look_times=None,
    total_look_duration_ms=0,
    age_group=None,
    gender=None,
    exposure_ms=1000,  # avg_dwell_time_ms, attention_rate_times 계산에 필요
):
    """테스트용 EventRaw 유사 객체 생성 헬퍼."""
    r = MagicMock(spec=EventRaw)
    r.look_times             = look_times or []
    r.total_look_duration_ms = total_look_duration_ms
    r.age_group              = age_group
    r.gender                 = gender
    r.exposure_ms            = exposure_ms
    return r


class TestBuildAggCounts:

    def test_빈_리스트_입력(self):
        result = _build_agg_counts([])
        assert result["exposure_count"]          == 0
        assert result["interested_count"]        == 0
        assert result["attention_rate_tracks"]   == 0.0
        assert result["total_attention_time_ms"] == 0.0
        assert result["avg_dwell_time_ms"]       == 0.0
        assert result["attention_rate_times"]    == 0.0

    def test_관심_인구_없음(self):
        rows = [
            row(look_times=[], age_group="30-39", gender="female", exposure_ms=2000),
            row(look_times=[], age_group="20-29", gender="male",   exposure_ms=1000),
            row(look_times=[], age_group=None,    gender=None,      exposure_ms=500),
        ]
        result = _build_agg_counts(rows)
        assert result["exposure_count"]          == 3
        assert result["interested_count"]        == 0
        assert result["attention_rate_tracks"]   == 0.0
        assert result["total_attention_time_ms"] == 0.0
        assert result["avg_dwell_time_ms"]       == round((2000 + 1000 + 500) / 3, 2)
        assert result["count_30s"]               == 1
        assert result["count_20s"]               == 1
        assert result["count_male"]              == 1
        assert result["count_female"]            == 1

    def test_AI팀_샘플_배치_7개_트랙(self):
        """
        AI팀이 제공한 샘플 JSON (track 7개) 기준 집계 검증.

        관심 인구: track 18 (840ms), track 25 (520ms) → 2명
        나이대: 10s=0, 20s=1, 30s=3, 40s=1, 50s=1, null=1
        성별: male=2, female=4, null=1
        """
        rows = [
            row(look_times=[],                                total_look_duration_ms=0,   age_group="30-39", gender="female", exposure_ms=2560),  # track 13
            row(look_times=[{"start_ms":0, "end_ms":840}],   total_look_duration_ms=840, age_group="20-29", gender="female", exposure_ms=1560),  # track 18 ← 관심
            row(look_times=[],                                total_look_duration_ms=0,   age_group="40-49", gender="male",   exposure_ms=2560),  # track 21
            row(look_times=[],                                total_look_duration_ms=0,   age_group="30-39", gender="female", exposure_ms=2560),  # track 22
            row(look_times=[],                                total_look_duration_ms=0,   age_group="50-59", gender="male",   exposure_ms=2560),  # track 23
            row(look_times=[],                                total_look_duration_ms=0,   age_group=None,    gender=None,      exposure_ms=80),    # track 24
            row(look_times=[{"start_ms":2040,"end_ms":2560}],total_look_duration_ms=520, age_group="30-39", gender="female", exposure_ms=960),   # track 25 ← 관심
        ]
        result = _build_agg_counts(rows)

        total_exposure_ms = 2560 + 1560 + 2560 + 2560 + 2560 + 80 + 960  # 12840

        assert result["exposure_count"]          == 7
        assert result["interested_count"]        == 2
        assert result["attention_rate_tracks"]   == round(2 / 7, 4)
        assert result["total_attention_time_ms"] == 840 + 520  # 1360
        assert result["avg_dwell_time_ms"]       == round(total_exposure_ms / 7, 2)
        assert result["attention_rate_times"]    == round(1360 / total_exposure_ms, 4)

        assert result["count_10s"]      == 0
        assert result["count_20s"]      == 1
        assert result["count_30s"]      == 3
        assert result["count_40s"]      == 1
        assert result["count_50s_plus"] == 1

        assert result["count_male"]   == 2
        assert result["count_female"] == 4

    def test_unknown_age_group_은_무시된다(self):
        rows = [row(age_group="unknown", gender="male")]
        result = _build_agg_counts(rows)
        assert result["count_10s"] == result["count_20s"] == result["count_30s"] == 0

    def test_attention_rate_tracks_소수점_4자리(self):
        # 1/3 = 0.3333
        rows = [
            row(look_times=[{"start_ms":0,"end_ms":100}], total_look_duration_ms=100, exposure_ms=1000),
            row(look_times=[], exposure_ms=1000),
            row(look_times=[], exposure_ms=1000),
        ]
        result = _build_agg_counts(rows)
        assert result["attention_rate_tracks"] == round(1 / 3, 4)

    def test_attention_time_관심_인구만_계산(self):
        """관심 없는 사람의 total_look_duration_ms는 total_attention_time_ms에 포함되지 않아야 함"""
        rows = [
            row(look_times=[{"start_ms":0,"end_ms":1000}], total_look_duration_ms=1000, exposure_ms=2000),
            row(look_times=[{"start_ms":0,"end_ms":3000}], total_look_duration_ms=3000, exposure_ms=4000),
            row(look_times=[],                             total_look_duration_ms=9999, exposure_ms=1000),  # 관심 없음
        ]
        result = _build_agg_counts(rows)
        assert result["total_attention_time_ms"] == 1000 + 3000  # 4000
        assert result["avg_dwell_time_ms"]       == round((2000 + 4000 + 1000) / 3, 2)
        assert result["attention_rate_times"]    == round(4000 / (2000 + 4000 + 1000), 4)