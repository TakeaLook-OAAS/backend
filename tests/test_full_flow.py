"""
전체 흐름 통합 테스트: POST /events/ → events_raw 저장 → DailyAgg 집계

테스트 시나리오:
  1. seed 픽스처로 Device / Campaign / DeviceCampaign 데이터 삽입
  2. POST /events/ 로 AI팀 샘플 배치 전송
  3. events_raw, segment_logs 저장 여부 확인
  4. run_daily_aggregation() 실행
  5. DailyAgg 집계 수치 검증
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date, datetime, timezone

from models import EventRaw, SegmentLog, DailyAgg, HourlyAgg
from Aggregation import run_daily_aggregation, run_hourly_aggregation


# ── 샘플 배치 페이로드 (AI팀 전달 JSON 기준) ─────────────────────────────────

def make_payload(device_id: str, cycle_index: int = 1) -> dict:
    return {
        "segment": {
            "device_id":   device_id,
            "index":       7,
            "cycle_index": cycle_index,
            "timestamp":   "2026-03-27T09:36:47.958388+00:00",
            "duration_ms": 3000,
            "roi_polygon": [[0,0],[1920,0],[1920,1080],[0,1080]],
        },
        "tracks": [
            {
                "track_id": 13,
                "exposure": {"start_ms": 0, "end_ms": 2560},
                "look_times": [],
                "total_look_duration_ms": 0,
                "age_group": "30-39",
                "gender": "female",
            },
            {
                "track_id": 18,
                "exposure": {"start_ms": 0, "end_ms": 1560},
                "look_times": [{"start_ms": 0, "end_ms": 840, "in_roi": True}],
                "total_look_duration_ms": 840,
                "age_group": "20-29",
                "gender": "female",
            },
            {
                "track_id": 21,
                "exposure": {"start_ms": 0, "end_ms": 2560},
                "look_times": [],
                "total_look_duration_ms": 0,
                "age_group": "40-49",
                "gender": "male",
            },
            {
                "track_id": 22,
                "exposure": {"start_ms": 0, "end_ms": 2560},
                "look_times": [],
                "total_look_duration_ms": 0,
                "age_group": "30-39",
                "gender": "female",
            },
            {
                "track_id": 23,
                "exposure": {"start_ms": 0, "end_ms": 2560},
                "look_times": [],
                "total_look_duration_ms": 0,
                "age_group": "50-59",
                "gender": "male",
            },
            {
                "track_id": 24,
                "exposure": {"start_ms": 880, "end_ms": 960},
                "look_times": [],
                "total_look_duration_ms": 0,
                "age_group": None,
                "gender": None,
            },
            {
                "track_id": 25,
                "exposure": {"start_ms": 1600, "end_ms": 2560},
                "look_times": [{"start_ms": 2040, "end_ms": 2560, "in_roi": True}],
                "total_look_duration_ms": 520,
                "age_group": "30-39",
                "gender": "female",
            },
        ],
    }


# ── 1단계: API 저장 테스트 ────────────────────────────────────────────────────

class TestPostEvents:

    def test_정상_배치_수신_202(self, client, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        res = client.post("/events/", json=payload)
        assert res.status_code == 202
        assert res.json()["inserted"] == 7
        assert res.json()["status"] == "success"

    def test_events_raw_7행_저장(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        rows = db.query(EventRaw).all()
        assert len(rows) == 7

    def test_segment_log_1행_저장(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        logs = db.query(SegmentLog).all()
        assert len(logs) == 1
        assert logs[0].cycle_index == seed["cycle_index"]
        assert logs[0].duration_ms == 3000

    def test_unknown_age_group_None으로_저장(self, client, db, seed):
        """track 24는 age_group=null → events_raw.age_group IS NULL"""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        track24 = db.query(EventRaw).filter_by(track_id=24).first()
        assert track24 is not None
        assert track24.age_group is None
        assert track24.gender    is None

    def test_잘못된_UUID_형식_400(self, client, seed):
        payload = make_payload("not-a-uuid", seed["cycle_index"])
        res = client.post("/events/", json=payload)
        assert res.status_code == 400

    def test_미등록_기기_401(self, client, seed):
        import uuid
        payload = make_payload(str(uuid.uuid4()), seed["cycle_index"])
        res = client.post("/events/", json=payload)
        assert res.status_code == 401

    def test_없는_cycle_index_404(self, client, seed):
        payload = make_payload(str(seed["device_id"]), cycle_index=999)
        res = client.post("/events/", json=payload)
        assert res.status_code == 404

    def test_중복_배치_409(self, client, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)           # 첫 번째 전송
        res = client.post("/events/", json=payload)     # 동일 배치 재전송
        assert res.status_code == 409


# ── 2단계: 집계 로직 테스트 ───────────────────────────────────────────────────

class TestAggregation:

    TARGET_DATE = date(2026, 3, 27)

    def test_daily_agg_1행_생성(self, client, db, seed):
        """배치 저장 후 run_daily_aggregation() → DailyAgg 1행 생성."""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()  # 세션 캐시 초기화

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        results = db.query(DailyAgg).all()
        assert len(results) == 1

    def test_daily_agg_exposure_count_7(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.exposure_count == 7

    def test_daily_agg_interested_count_2(self, client, db, seed):
        """look_times가 있는 track: 18, 25 → 2명"""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.interested_count == 2

    def test_daily_agg_attention_rate(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.attention_rate == round(2 / 7, 4)

    def test_daily_agg_avg_viewing_time(self, client, db, seed):
        """관심 인구(track 18: 840ms, track 25: 520ms) 평균 → 680.0ms"""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.avg_viewing_time_ms == 680.0

    def test_daily_agg_age_counts(self, client, db, seed):
        """나이대별 카운트: 20s=1, 30s=3, 40s=1, 50s=1, null=미집계"""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.count_10s      == 0
        assert agg.count_20s      == 1
        assert agg.count_30s      == 3
        assert agg.count_40s      == 1
        assert agg.count_50s_plus == 1

    def test_daily_agg_gender_counts(self, client, db, seed):
        """성별 카운트: male=2 (track 21,23), female=4 (track 13,18,22,25)"""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.count_male   == 2
        assert agg.count_female == 4

    def test_daily_agg_device_campaign_연결(self, client, db, seed):
        """DailyAgg의 device_id, campaign_id가 올바르게 연결됐는지 확인."""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)

        agg = db.query(DailyAgg).first()
        assert agg.device_id   == seed["device_id"]
        assert agg.campaign_id == seed["campaign_id"]

    def test_daily_agg_중복_실행시_UPDATE(self, client, db, seed):
        """집계 함수를 두 번 실행해도 행이 1개이고 값이 덮어써진다."""
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)
        db.expire_all()

        run_daily_aggregation(db, target_date=self.TARGET_DATE)
        run_daily_aggregation(db, target_date=self.TARGET_DATE)  # 재실행

        count = db.query(DailyAgg).count()
        assert count == 1

    def test_데이터_없는_날짜는_집계_스킵(self, db, seed):
        """events_raw가 없는 날짜는 DailyAgg를 생성하지 않는다."""
        run_daily_aggregation(db, target_date=date(2099, 1, 1))
        assert db.query(DailyAgg).count() == 0


# ── 3단계: GET /events/ 조회 테스트 ──────────────────────────────────────────

class TestGetEvents:

    def test_전체_조회(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        res = client.get("/events/")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 7
        assert len(data["events"]) == 7

    def test_device_id_필터(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        res = client.get(f"/events/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] == 7

    def test_campaign_id_필터(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        res = client.get(f"/events/?campaign_id={seed['campaign_id']}")
        assert res.status_code == 200
        assert res.json()["total"] == 7

    def test_limit_파라미터(self, client, db, seed):
        payload = make_payload(str(seed["device_id"]), seed["cycle_index"])
        client.post("/events/", json=payload)

        res = client.get("/events/?limit=3")
        assert res.status_code == 200
        assert res.json()["total"] == 3
