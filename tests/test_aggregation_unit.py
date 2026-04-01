"""
Aggregation._build_agg_counts() 단위 테스트

DB 없이 순수 Python 로직만 검증.
AI팀 샘플 JSON을 기반으로 집계 수치가 올바른지 확인.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from models import EventRaw
from Aggregation import _build_agg_counts


def row(look_times=None, total_look_duration_ms=0, age_group=None, gender=None):
    """테스트용 EventRaw 유사 객체 생성 헬퍼."""
    r = MagicMock(spec=EventRaw)
    r.look_times             = look_times or []
    r.total_look_duration_ms = total_look_duration_ms
    r.age_group              = age_group
    r.gender                 = gender
    return r


class TestBuildAggCounts:

    def test_빈_리스트_입력(self):
        result = _build_agg_counts([])
        assert result["exposure_count"]      == 0
        assert result["interested_count"]    == 0
        assert result["attention_rate"]      == 0.0
        assert result["avg_viewing_time_ms"] == 0.0

    def test_관심_인구_없음(self):
        rows = [
            row(look_times=[],  age_group="30-39", gender="female"),
            row(look_times=[],  age_group="20-29", gender="male"),
            row(look_times=[],  age_group=None,    gender=None),
        ]
        result = _build_agg_counts(rows)
        assert result["exposure_count"]      == 3
        assert result["interested_count"]    == 0
        assert result["attention_rate"]      == 0.0
        assert result["avg_viewing_time_ms"] == 0.0
        assert result["count_30s"]           == 1
        assert result["count_20s"]           == 1
        assert result["count_male"]          == 1
        assert result["count_female"]        == 1

    def test_AI팀_샘플_배치_7개_트랙(self):
        """
        AI팀이 제공한 샘플 JSON (track 7개) 기준 집계 검증.

        관심 인구: track 18 (840ms), track 25 (520ms) → 2명
        나이대: 10s=0, 20s=1, 30s=3, 40s=1, 50s=1, null=1
        성별: male=2, female=4, null=1
        """
        rows = [
            row(look_times=[],                                total_look_duration_ms=0,   age_group="30-39", gender="female"),  # track 13
            row(look_times=[{"start_ms":0, "end_ms":840}],   total_look_duration_ms=840, age_group="20-29", gender="female"),  # track 18 ← 관심
            row(look_times=[],                                total_look_duration_ms=0,   age_group="40-49", gender="male"),    # track 21
            row(look_times=[],                                total_look_duration_ms=0,   age_group="30-39", gender="female"),  # track 22
            row(look_times=[],                                total_look_duration_ms=0,   age_group="50-59", gender="male"),    # track 23
            row(look_times=[],                                total_look_duration_ms=0,   age_group=None,    gender=None),      # track 24
            row(look_times=[{"start_ms":2040,"end_ms":2560}],total_look_duration_ms=520, age_group="30-39", gender="female"),  # track 25 ← 관심
        ]
        result = _build_agg_counts(rows)

        assert result["exposure_count"]      == 7
        assert result["interested_count"]    == 2
        assert result["attention_rate"]      == round(2 / 7, 4)   # 0.2857
        assert result["avg_viewing_time_ms"] == round((840 + 520) / 2, 2)  # 680.0

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

    def test_attention_rate_소수점_4자리(self):
        # 1/3 = 0.3333
        rows = [
            row(look_times=[{"start_ms":0,"end_ms":100}], total_look_duration_ms=100),
            row(look_times=[]),
            row(look_times=[]),
        ]
        result = _build_agg_counts(rows)
        assert result["attention_rate"] == round(1 / 3, 4)

    def test_avg_viewing_time_관심_인구만_계산(self):
        # 관심 없는 사람의 total_look_duration_ms는 avg에 포함되지 않아야 함
        rows = [
            row(look_times=[{"start_ms":0,"end_ms":1000}], total_look_duration_ms=1000),
            row(look_times=[{"start_ms":0,"end_ms":3000}], total_look_duration_ms=3000),
            row(look_times=[],                             total_look_duration_ms=9999),  # 관심 없음
        ]
        result = _build_agg_counts(rows)
        assert result["avg_viewing_time_ms"] == round((1000 + 3000) / 2, 2)  # 2000.0
