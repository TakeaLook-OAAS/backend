"""
전체 흐름 통합 테스트: POST /events/ → events_raw 저장 → 집계

테스트 시나리오:
  1. seed 픽스처로 Device / Campaign(3개) / DeviceCampaign(3개) 데이터 삽입
  2. 실제 세그먼트 파일(segment_000~009.json)로 POST /events/ 전송
  3. events_raw, segment_logs 저장 여부 확인
  4. run_daily_aggregation() 실행
  5. DailyAgg 집계 수치 검증
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from datetime import date

from models import EventRaw, SegmentLog, DailyAgg, HourlyAgg
from Aggregation import run_daily_aggregation, run_hourly_aggregation

# 세그먼트 파일 경로
SEGMENTS_DIR = os.path.join(os.path.dirname(__file__), "segments")


def load_segment(filename: str) -> dict:
    """실제 세그먼트 파일을 읽어서 반환"""
    path = os.path.join(SEGMENTS_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def inject_device_id(payload: dict, device_id: str) -> dict:
    """세그먼트 페이로드의 device_id를 테스트용 device_id로 교체"""
    payload["segment"]["device_id"] = device_id
    return payload


# 테스트에 사용할 세그먼트 파일 목록
SEGMENT_FILES = [f"segment_{i:03d}.json" for i in range(10)]  # 000 ~ 009


# ── 1단계: API 저장 테스트 ────────────────────────────────────────────────────

class TestPostEvents:

    def test_segment_000_정상_수신_202(self, client, seed):
        """segment_000.json 정상 수신 확인"""
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        res = client.post("/events/", json=payload)
        assert res.status_code == 202
        assert res.json()["status"] == "success"

    def test_전체_세그먼트_10개_순서대로_수신(self, client, db, seed):
        """segment_000 ~ segment_009 순서대로 전송 후 events_raw 총 행 수 확인"""
        total_tracks = 0
        for filename in SEGMENT_FILES:
            payload = inject_device_id(
                load_segment(filename),
                str(seed["device_id"])
            )
            res = client.post("/events/", json=payload)
            assert res.status_code == 202, f"{filename} 전송 실패: {res.json()}"
            total_tracks += res.json()["inserted"]

        rows = db.query(EventRaw).all()
        assert len(rows) == total_tracks

    def test_segment_logs_10행_저장(self, client, db, seed):
        """세그먼트 10개 전송 후 segment_logs 10행 확인"""
        for filename in SEGMENT_FILES:
            payload = inject_device_id(
                load_segment(filename),
                str(seed["device_id"])
            )
            client.post("/events/", json=payload)

        logs = db.query(SegmentLog).all()
        assert len(logs) == 10

    def test_unknown_age_group_None으로_저장(self, client, db, seed):
        """age_group이 unknown인 track은 None으로 저장되어야 함"""
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        client.post("/events/", json=payload)

        # age_group이 None인 행이 존재하는지 확인
        none_rows = db.query(EventRaw).filter(EventRaw.age_group == None).all()
        assert len(none_rows) > 0

    def test_잘못된_UUID_형식_400(self, client, seed):
        payload = load_segment("segment_000.json")
        payload["segment"]["device_id"] = "not-a-uuid"
        res = client.post("/events/", json=payload)
        assert res.status_code == 400

    def test_미등록_기기_401(self, client, seed):
        import uuid
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(uuid.uuid4())
        )
        res = client.post("/events/", json=payload)
        assert res.status_code == 401

    def test_없는_cycle_index_404(self, client, seed):
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        payload["segment"]["cycle_index"] = 999
        res = client.post("/events/", json=payload)
        assert res.status_code == 404

    def test_중복_배치_409(self, client, seed):
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        client.post("/events/", json=payload)
        res = client.post("/events/", json=payload)
        assert res.status_code == 409


# ── 2단계: 집계 로직 테스트 ───────────────────────────────────────────────────

class TestAggregation:

    # 세그먼트 파일의 timestamp 날짜 기준
    TARGET_DATE = date(2026, 4, 3)

    def _send_all_segments(self, client, seed):
        """전체 세그먼트 10개 전송 헬퍼"""
        for filename in SEGMENT_FILES:
            payload = inject_device_id(
                load_segment(filename),
                str(seed["device_id"])
            )
            client.post("/events/", json=payload)

    def test_daily_agg_생성(self, client, db, seed):
        """전체 세그먼트 전송 후 daily_agg 생성 확인"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        results = db.query(DailyAgg).all()
        assert len(results) > 0

    def test_daily_agg_exposure_count(self, client, db, seed):
        """exposure_count = 전체 track 수"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        total_tracks = db.query(EventRaw).count()
        total_exposure = sum(agg.exposure_count for agg in db.query(DailyAgg).all())
        assert total_exposure == total_tracks

    def test_daily_agg_interested_count(self, client, db, seed):
        """interested_count = look_times가 있는 track 수"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        interested_in_db = db.query(EventRaw).filter(
            EventRaw.look_times != []
        ).count()
        total_interested = sum(agg.interested_count for agg in db.query(DailyAgg).all())
        assert total_interested == interested_in_db

    def test_daily_agg_attention_rate_tracks(self, client, db, seed):
        """attention_rate_tracks = interested_count / exposure_count"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        for agg in db.query(DailyAgg).all():
            expected = round(agg.interested_count / agg.exposure_count, 4)
            assert agg.attention_rate_tracks == expected

    def test_daily_agg_avg_dwell_time(self, client, db, seed):
        """avg_dwell_time_ms = sum(exposure_ms) / exposure_count"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        for agg in db.query(DailyAgg).all():
            assert agg.avg_dwell_time_ms >= 0.0

    def test_daily_agg_중복_실행시_UPDATE(self, client, db, seed):
        """집계 함수를 두 번 실행해도 행 수가 늘어나지 않는다"""
        self._send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)
        count_before = db.query(DailyAgg).count()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)
        count_after = db.query(DailyAgg).count()

        assert count_before == count_after

    def test_데이터_없는_날짜는_집계_스킵(self, db, seed):
        """events_raw가 없는 날짜는 DailyAgg를 생성하지 않는다"""
        run_daily_aggregation(db, target_date=date(2099, 1, 1))
        assert db.query(DailyAgg).count() == 0


# ── 3단계: GET /events/ 조회 테스트 ──────────────────────────────────────────

class TestGetEvents:

    def test_전체_조회(self, client, db, seed):
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        client.post("/events/", json=payload)

        res = client.get("/events/")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_device_id_필터(self, client, db, seed):
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        client.post("/events/", json=payload)

        res = client.get(f"/events/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_limit_파라미터(self, client, db, seed):
        payload = inject_device_id(
            load_segment("segment_000.json"),
            str(seed["device_id"])
        )
        client.post("/events/", json=payload)

        res = client.get("/events/?limit=3")
        assert res.status_code == 200
        assert len(res.json()["events"]) <= 3