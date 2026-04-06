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
from sqlalchemy import func
from models import EventRaw, SegmentLog, DailyAgg, HourlyAgg, CampaignAgg
from Aggregation import run_daily_aggregation, run_hourly_aggregation, run_campaign_aggregation
import models

SEGMENTS_DIR = os.path.join(os.path.dirname(__file__), "segments")
SEGMENT_FILES = [f"segment_{i:03d}.json" for i in range(10)]  # 000 ~ 009
TARGET_DATE = date(2026, 4, 3)  # 세그먼트 파일 timestamp 날짜


def load_segment(filename: str) -> dict:
    path = os.path.join(SEGMENTS_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def inject_device_id(payload: dict, device_id: str) -> dict:
    payload["segment"]["device_id"] = device_id
    return payload


def send_all_segments(client, seed):
    """전체 세그먼트 10개 전송 헬퍼"""
    for filename in SEGMENT_FILES:
        payload = inject_device_id(load_segment(filename), str(seed["device_id"]))
        res = client.post("/events/", json=payload)
        assert res.status_code == 202, f"{filename} 전송 실패: {res.json()}"


# ── 1단계: POST /events/ 저장 테스트 ─────────────────────────────────────────

class TestPostEvents:

    def test_정상_수신_202(self, client, seed):
        """segment_000.json 정상 수신 → 202 반환"""
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        res = client.post("/events/", json=payload)
        assert res.status_code == 202
        assert res.json()["status"] == "success"

    def test_전체_세그먼트_10개_events_raw_저장(self, client, db, seed):
        """10개 세그먼트 전송 후 events_raw 총 행 수 = 각 파일 inserted 합계"""
        total_inserted = 0
        for filename in SEGMENT_FILES:
            payload = inject_device_id(load_segment(filename), str(seed["device_id"]))
            res = client.post("/events/", json=payload)
            assert res.status_code == 202, f"{filename} 실패: {res.json()}"
            total_inserted += res.json()["inserted"]

        assert db.query(EventRaw).count() == total_inserted

    def test_segment_logs_10행_저장(self, client, db, seed):
        """10개 세그먼트 전송 후 segment_logs 정확히 10행"""
        send_all_segments(client, seed)
        assert db.query(SegmentLog).count() == 10

    def test_unknown_age_group_None으로_저장(self, client, db, seed):
        """age_group이 unknown인 track → DB에 None으로 저장"""
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        client.post("/events/", json=payload)
        assert db.query(EventRaw).filter(EventRaw.age_group == None).count() > 0

    def test_잘못된_UUID_형식_400(self, client, seed):
        payload = load_segment("segment_000.json")
        payload["segment"]["device_id"] = "not-a-uuid"
        res = client.post("/events/", json=payload)
        assert res.status_code == 400

    def test_미등록_기기_401(self, client, seed):
        import uuid
        payload = inject_device_id(load_segment("segment_000.json"), str(uuid.uuid4()))
        res = client.post("/events/", json=payload)
        assert res.status_code == 401

    def test_없는_cycle_index_404(self, client, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        payload["segment"]["cycle_index"] = 999
        res = client.post("/events/", json=payload)
        assert res.status_code == 404

    def test_중복_배치_409(self, client, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        client.post("/events/", json=payload)
        res = client.post("/events/", json=payload)
        assert res.status_code == 409


# ── 2단계: 집계 로직 테스트 ───────────────────────────────────────────────────

class TestAggregation:

    def test_daily_agg_생성(self, client, db, seed):
        """10개 세그먼트 전송 후 DailyAgg 행이 1개 이상 생성되어야 함"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)
        assert db.query(DailyAgg).count() > 0

    def test_daily_agg_exposure_count(self, client, db, seed):
        """DailyAgg exposure_count 합계 = TARGET_DATE의 events_raw track 수"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)

        # 집계 대상과 동일한 날짜 필터로 track 수 산출
        total_tracks = (
            db.query(EventRaw)
            .filter(func.date(func.timezone('UTC', EventRaw.ts)) == TARGET_DATE)
            .count()
        )
        total_exposure = sum(agg.exposure_count for agg in db.query(DailyAgg).all())
        assert total_exposure == total_tracks

    def test_daily_agg_interested_count(self, client, db, seed):
        """DailyAgg interested_count 합계 = look_times가 있는 track 수"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)

        interested_in_db = (
            db.query(EventRaw)
            .filter(
                func.date(func.timezone('UTC', EventRaw.ts)) == TARGET_DATE,
                EventRaw.look_times != []
            )
            .count()
        )
        total_interested = sum(agg.interested_count for agg in db.query(DailyAgg).all())
        assert total_interested == interested_in_db

    def test_daily_agg_attention_rate_tracks(self, client, db, seed):
        """각 DailyAgg의 attention_rate_tracks = interested_count / exposure_count"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)

        for agg in db.query(DailyAgg).all():
            expected = round(agg.interested_count / agg.exposure_count, 4)
            assert agg.attention_rate_tracks == expected

    def test_daily_agg_avg_dwell_time_양수(self, client, db, seed):
        """avg_dwell_time_ms는 0 이상이어야 함"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)

        for agg in db.query(DailyAgg).all():
            assert agg.avg_dwell_time_ms >= 0.0

    def test_daily_agg_중복_실행시_UPDATE(self, client, db, seed):
        """집계 함수를 두 번 실행해도 DailyAgg 행 수가 늘어나지 않음"""
        send_all_segments(client, seed)
        db.expire_all()

        run_daily_aggregation(db, target_date=TARGET_DATE)
        count_before = db.query(DailyAgg).count()

        run_daily_aggregation(db, target_date=TARGET_DATE)
        count_after = db.query(DailyAgg).count()

        assert count_before == count_after

    def test_데이터_없는_날짜는_집계_스킵(self, db, seed):
        """events_raw가 없는 날짜는 DailyAgg를 생성하지 않음"""
        run_daily_aggregation(db, target_date=date(2099, 1, 1))
        assert db.query(DailyAgg).count() == 0


# ── 3단계: GET /events/ 조회 테스트 ──────────────────────────────────────────

class TestGetEvents:

    def test_전체_조회(self, client, db, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        client.post("/events/", json=payload)
        res = client.get("/events/")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_device_id_필터(self, client, db, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        client.post("/events/", json=payload)
        res = client.get(f"/events/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_limit_파라미터(self, client, db, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        client.post("/events/", json=payload)
        res = client.get("/events/?limit=3")
        assert res.status_code == 200
        assert len(res.json()["events"]) <= 3

# ── 4단계: GET /stats/ 조회 테스트 ───────────────────────────────────────────

class TestStats:

    def _setup(self, client, db, seed):
        """세그먼트 전송 + 집계 실행 헬퍼"""
        send_all_segments(client, seed)
        db.expire_all()
        run_daily_aggregation(db, target_date=TARGET_DATE)
        run_hourly_aggregation(db, target_date=TARGET_DATE)
        from Aggregation import run_campaign_aggregation
        run_campaign_aggregation(db)

    # ── daily ─────────────────────────────────────────────────────────────────

    def test_daily_전체_조회(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get("/stats/daily/")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_daily_device_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/daily/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_daily_campaign_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        campaign_id = seed["campaign_ids"][0]
        res = client.get(f"/stats/daily/?campaign_id={campaign_id}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_daily_target_date_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/daily/?target_date={TARGET_DATE}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_daily_날짜_범위_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/daily/?start_date=2026-04-01&end_date=2026-04-30")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_daily_결과_없는_날짜(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get("/stats/daily/?target_date=2099-01-01")
        assert res.status_code == 200
        assert res.json()["total"] == 0

    # ── hourly ────────────────────────────────────────────────────────────────

    def test_hourly_전체_조회(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get("/stats/hourly/")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_hourly_device_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/hourly/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_hourly_campaign_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        campaign_id = seed["campaign_ids"][0]
        res = client.get(f"/stats/hourly/?campaign_id={campaign_id}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_hourly_target_date_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/hourly/?target_date={TARGET_DATE}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_hourly_결과_없는_날짜(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get("/stats/hourly/?target_date=2099-01-01")
        assert res.status_code == 200
        assert res.json()["total"] == 0

    # ── campaign ──────────────────────────────────────────────────────────────

    def test_campaign_전체_조회(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get("/stats/campaign/")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_campaign_device_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        res = client.get(f"/stats/campaign/?device_id={seed['device_id']}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    def test_campaign_campaign_id_필터(self, client, db, seed):
        self._setup(client, db, seed)
        campaign_id = seed["campaign_ids"][0]
        res = client.get(f"/stats/campaign/?campaign_id={campaign_id}")
        assert res.status_code == 200
        assert res.json()["total"] > 0

    # ── golden-zone ───────────────────────────────────────────────────────────

    def test_golden_zone_데이터_없으면_404(self, client, db, seed):
        """DbscanAgg 데이터 없을 때 404 반환"""
        campaign_id = seed["campaign_ids"][0]
        res = client.get(f"/stats/golden-zone/?campaign_id={campaign_id}&device_id={seed['device_id']}")
        assert res.status_code == 404

    def test_golden_zone_데이터_있으면_200(self, client, db, seed):
        """DbscanAgg 데이터 직접 삽입 후 200 반환 및 응답 구조 확인"""
        campaign_id = seed["campaign_ids"][0]

        # DbscanAgg 테스트 데이터 직접 삽입
        db.add(models.DbscanAgg(
            campaign_id         = campaign_id,
            device_id           = seed["device_id"],
            eps                 = 30.0,
            min_samples         = 5,
            n_interp            = 10,
            point_count         = 100,
            event_count         = 50,
            noise_count         = 5,
            cluster_count       = 2,
            cluster_label       = 0,
            is_main             = True,
            cluster_point_count = 80,
            convex_hull         = {"vertices": [[0,0],[100,0],[100,100],[0,100]], "area_px2": 10000.0},
            ellipse             = {"center": [50,50], "semi_axes": [50,50], "angle_deg": 0.0},
        ))
        db.commit()

        res = client.get(f"/stats/golden-zone/?campaign_id={campaign_id}&device_id={seed['device_id']}")
        assert res.status_code == 200

        data = res.json()
        assert "clusters" in data
        assert len(data["clusters"]) > 0
        assert "dbscan" in data
        assert data["clusters"][0]["is_main"] is True