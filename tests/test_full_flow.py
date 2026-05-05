"""
전체 흐름 통합 테스트: POST /events/ → events_raw 저장 → 집계
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from datetime import date
from sqlalchemy import func
from models import EventRaw, SegmentLog, CampaignAgg, CampaignAdvancedAgg
from Aggregation import run_campaign_aggregation, run_advanced_aggregation
import models

SEGMENTS_DIR = os.path.join(os.path.dirname(__file__), "segments")
SEGMENT_FILES = [f"segment_{i:03d}.json" for i in range(10)]
TARGET_DATE = date(2026, 4, 3)


def load_segment(filename: str) -> dict:
    path = os.path.join(SEGMENTS_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def inject_device_id(payload: dict, device_id: str) -> dict:
    payload["segment"]["device_id"] = device_id
    return payload


def send_all_segments(client, seed):
    for filename in SEGMENT_FILES:
        payload = inject_device_id(load_segment(filename), str(seed["device_id"]))
        res = client.post("/events/", json=payload)
        assert res.status_code == 202, f"{filename} 전송 실패: {res.json()}"


# ── 1단계: POST /events/ 저장 테스트 ─────────────────────────────────────────

class TestPostEvents:

    def test_정상_수신_202(self, client, seed):
        payload = inject_device_id(load_segment("segment_000.json"), str(seed["device_id"]))
        res = client.post("/events/", json=payload)
        assert res.status_code == 202
        assert res.json()["status"] == "success"

    def test_전체_세그먼트_10개_events_raw_저장(self, client, db, seed):
        total_inserted = 0
        for filename in SEGMENT_FILES:
            payload = inject_device_id(load_segment(filename), str(seed["device_id"]))
            res = client.post("/events/", json=payload)
            assert res.status_code == 202, f"{filename} 실패: {res.json()}"
            total_inserted += res.json()["inserted"]
        assert db.query(EventRaw).count() == total_inserted

    def test_segment_logs_10행_저장(self, client, db, seed):
        send_all_segments(client, seed)
        assert db.query(SegmentLog).count() == 10

    def test_unknown_age_group_None으로_저장(self, client, db, seed):
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

    def test_campaign_agg_생성(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_campaign_aggregation(db)
        assert db.query(CampaignAgg).count() > 0

    def test_campaign_agg_exposure_count(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_campaign_aggregation(db)

        total_tracks   = db.query(EventRaw).count()
        total_exposure = sum(agg.exposure_count for agg in db.query(CampaignAgg).all())
        assert total_exposure == total_tracks

    def test_campaign_agg_interested_count(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_campaign_aggregation(db)

        # 5번 수정: jsonb_array_length 사용
        interested_in_db = (
            db.query(EventRaw)
            .filter(func.jsonb_array_length(EventRaw.look_times) > 0)
            .count()
        )
        total_interested = sum(agg.interested_count for agg in db.query(CampaignAgg).all())
        assert total_interested == interested_in_db

    def test_campaign_agg_attention_rate_tracks(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_campaign_aggregation(db)

        for agg in db.query(CampaignAgg).all():
            expected = round(agg.interested_count / agg.exposure_count, 4)
            assert agg.attention_rate_tracks == expected

    def test_campaign_agg_중복_실행시_UPDATE(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()

        run_campaign_aggregation(db)
        count_before = db.query(CampaignAgg).count()

        run_campaign_aggregation(db)
        count_after = db.query(CampaignAgg).count()

        assert count_before == count_after

    def test_데이터_없으면_집계_스킵(self, db, seed):
        run_campaign_aggregation(db)
        assert db.query(CampaignAgg).count() == 0

    def test_advanced_agg_생성(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_advanced_aggregation(db)
        assert db.query(CampaignAdvancedAgg).count() > 0

    def test_advanced_agg_avg_revisit_count_양수(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_advanced_aggregation(db)

        for agg in db.query(CampaignAdvancedAgg).all():
            assert agg.avg_revisit_count >= 0.0

    def test_advanced_agg_reactance_rate_범위(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()
        run_advanced_aggregation(db)

        for agg in db.query(CampaignAdvancedAgg).all():
            assert 0.0 <= agg.reactance_rate <= 1.0

    def test_advanced_agg_중복_실행시_UPDATE(self, client, db, seed):
        send_all_segments(client, seed)
        db.expire_all()

        run_advanced_aggregation(db)
        count_before = db.query(CampaignAdvancedAgg).count()

        run_advanced_aggregation(db)
        count_after = db.query(CampaignAdvancedAgg).count()

        assert count_before == count_after


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
        send_all_segments(client, seed)
        db.expire_all()
        run_campaign_aggregation(db)
        run_advanced_aggregation(db)

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
        campaign_id = seed["campaign_ids"][0]
        res = client.get(f"/stats/golden-zone/?campaign_id={campaign_id}&device_id={seed['device_id']}")
        assert res.status_code == 404

    def test_golden_zone_데이터_있으면_200(self, client, db, seed):
        campaign_id = seed["campaign_ids"][0]
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
            cluster_point_count = 80,
            points              = [[10, 20], [30, 40], [50, 60]],
        ))
        db.commit()

        res = client.get(f"/stats/golden-zone/?campaign_id={campaign_id}&device_id={seed['device_id']}")
        assert res.status_code == 200
        data = res.json()
        assert "clusters" in data
        assert len(data["clusters"]) > 0
        assert "dbscan" in data

    # ── range ─────────────────────────────────────────────────────────────────

    def test_range_정상_조회(self, client, db, seed):
        send_all_segments(client, seed)
        campaign_id = seed["campaign_ids"][0]
        res = client.get(
            f"/stats/range/?start_date=2026-04-01&end_date=2026-04-30"
            f"&device_id={seed['device_id']}&campaign_id={campaign_id}"
        )
        assert res.status_code == 200
        data = res.json()
        assert "exposure_count" in data
        assert "hourly_trend" in data
        assert "daily_trend" in data
        assert len(data["hourly_trend"]) == 24

    def test_range_데이터_없어도_200(self, client, db, seed):
        campaign_id = seed["campaign_ids"][0]
        res = client.get(
            f"/stats/range/?start_date=2099-01-01&end_date=2099-01-31"
            f"&device_id={seed['device_id']}&campaign_id={campaign_id}"
        )
        assert res.status_code == 200
        assert res.json()["exposure_count"] == 0

    def test_range_start_date_end_date_역전_400(self, client, db, seed):
        campaign_id = seed["campaign_ids"][0]
        res = client.get(
            f"/stats/range/?start_date=2026-04-30&end_date=2026-04-01"
            f"&device_id={seed['device_id']}&campaign_id={campaign_id}"
        )
        assert res.status_code == 400

    def test_range_잘못된_device_campaign_조합_404(self, client, db, seed):
        import uuid
        res = client.get(
            f"/stats/range/?start_date=2026-04-01&end_date=2026-04-30"
            f"&device_id={seed['device_id']}&campaign_id={uuid.uuid4()}"
        )
        assert res.status_code == 404