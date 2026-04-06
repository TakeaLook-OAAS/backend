"""
골든존 분석 로직
─────────────────────────────────────────────────────────
1. look_times(start_center, end_center) → 선형보간 → 포인트 클라우드
2. DBSCAN → 클러스터 레이블 할당, 노이즈(-1) 제거
3. 각 클러스터마다 Convex Hull + Ellipse Fit
4. 결과를 dbscan_aggs 테이블에 저장
"""

import uuid
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull, QhullError
from sqlalchemy.orm import Session

import models


# ── 보간 ──────────────────────────────────────────────────────────────────────

def interpolate_look(start_center: list, end_center: list, n: int) -> list[list[float]]:
    """두 점 사이를 n개 점으로 선형보간합니다."""
    if not start_center or not end_center:
        return []
    sx, sy = start_center
    ex, ey = end_center
    if n == 1:
        return [[(sx + ex) / 2, (sy + ey) / 2]]
    return [
        [sx + (ex - sx) * t / (n - 1), sy + (ey - sy) * t / (n - 1)]
        for t in range(n)
    ]


def build_point_cloud(rows: list, n_interp: int) -> np.ndarray:
    """
    events_raw 행 목록에서 포인트 클라우드를 만듭니다.
    각 look_time의 start_center ~ end_center를 n_interp개로 보간합니다.
    """
    points: list[list[float]] = []
    for row in rows:
        for lt in row.look_times:
            sc = lt.get("start_center")
            ec = lt.get("end_center")
            points.extend(interpolate_look(sc, ec, n_interp))
    return np.array(points, dtype=float) if points else np.empty((0, 2))


# ── Hull / Ellipse ─────────────────────────────────────────────────────────────

def fit_convex_hull(pts: np.ndarray) -> dict | None:
    """Convex Hull을 계산합니다. 점이 3개 미만이거나 일직선이면 None."""
    if len(pts) < 3:
        return None
    try:
        hull = ConvexHull(pts)
        return {
            "vertices": pts[hull.vertices].tolist(),  # [[x,y], ...] 시계방향
            "area_px2": float(hull.volume),            # 2D에서 volume = 넓이
        }
    except QhullError:
        return None


def fit_ellipse(pts: np.ndarray) -> dict | None:
    """
    PCA 기반 타원 피팅.
    semi_axes: 2-sigma 반축 길이 (픽셀), [긴 축, 짧은 축]
    angle_deg: x축 기준 반시계 방향 (도)
    """
    if len(pts) < 5:
        return None
    center = pts.mean(axis=0)
    cov = np.cov(pts.T)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)

    order = eigenvalues.argsort()[::-1]
    eigenvalues  = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]

    semi_axes = (2 * np.sqrt(np.maximum(eigenvalues, 0))).tolist()
    angle_deg = float(np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0])))

    return {
        "center":    center.tolist(),
        "semi_axes": semi_axes,
        "angle_deg": angle_deg,
    }


# ── DBSCAN 분석 ────────────────────────────────────────────────────────────────

def run_golden_zone(
    rows:        list,
    eps:         float,
    min_samples: int,
    n_interp:    int,
) -> dict:
    """
    골든존 분석을 실행하고 결과 dict를 반환합니다.

    반환 구조:
    {
      "status": "ok" | "no_data" | "insufficient_data" | "no_cluster",
      "point_count": int,
      "event_count": int,
      "dbscan": { "eps", "min_samples", "cluster_count", "noise_count" },
      "clusters": [
        {
          "label": int,
          "point_count": int,
          "is_main": bool,
          "convex_hull": { "vertices", "area_px2" } | None,
          "ellipse": { "center", "semi_axes", "angle_deg" } | None,
        },
        ...
      ]
    }
    """
    pts = build_point_cloud(rows, n_interp)

    if len(pts) == 0:
        return {
            "status":      "no_data",
            "point_count": 0,
            "event_count": len(rows),
            "detail":      "start_center/end_center가 있는 look_times 데이터가 없습니다.",
        }

    if len(pts) < min_samples:
        return {
            "status":      "insufficient_data",
            "point_count": int(len(pts)),
            "event_count": len(rows),
            "detail":      f"포인트 수({len(pts)})가 min_samples({min_samples})보다 적습니다.",
        }

    labels: np.ndarray = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(pts)

    unique_labels = sorted(set(labels.tolist()) - {-1})
    noise_count   = int((labels == -1).sum())

    if not unique_labels:
        return {
            "status":      "no_cluster",
            "point_count": int(len(pts)),
            "event_count": len(rows),
            "dbscan": {
                "eps":           eps,
                "min_samples":   min_samples,
                "cluster_count": 0,
                "noise_count":   noise_count,
            },
            "clusters": [],
            "detail":   "유효한 클러스터를 찾지 못했습니다. eps/min_samples를 조정해보세요.",
        }

    main_label = max(unique_labels, key=lambda label: int((labels == label).sum()))

    clusters = []
    for label in unique_labels:
        cluster_pts = pts[labels == label]
        clusters.append({
            "label":       int(label),
            "point_count": int(len(cluster_pts)),
            "is_main":     label == main_label,
            "convex_hull": fit_convex_hull(cluster_pts),
            "ellipse":     fit_ellipse(cluster_pts),
        })

    clusters.sort(key=lambda c: c["point_count"], reverse=True)

    return {
        "status":      "ok",
        "point_count": int(len(pts)),
        "event_count": len(rows),
        "dbscan": {
            "eps":           eps,
            "min_samples":   min_samples,
            "cluster_count": len(unique_labels),
            "noise_count":   noise_count,
        },
        "clusters": clusters,
    }


# ── DB 저장 ────────────────────────────────────────────────────────────────────

def save_golden_zone(
    result:      dict,
    campaign_id: uuid.UUID,
    device_id:   uuid.UUID,
    eps:         float,
    min_samples: int,
    n_interp:    int,
    db:          Session,
) -> None:
    """
    run_golden_zone() 결과를 dbscan_aggs에 저장합니다.
    기존 (campaign_id, device_id) 행을 삭제하고 새로 씁니다.
    status가 "ok"인 경우에만 호출하세요.
    """
    # 기존 결과 삭제 (재계산 시 덮어쓰기)
    db.query(models.DbscanAgg).filter_by(
        campaign_id=campaign_id,
        device_id=device_id,
    ).delete(synchronize_session=False)

    computed_at   = datetime.now(timezone.utc)
    point_count   = result["point_count"]
    event_count   = result["event_count"]
    noise_count   = result["dbscan"]["noise_count"]
    cluster_count = result["dbscan"]["cluster_count"]

    rows = [
        models.DbscanAgg(
            campaign_id         = campaign_id,
            device_id           = device_id,
            computed_at         = computed_at,
            eps                 = eps,
            min_samples         = min_samples,
            n_interp            = n_interp,
            point_count         = point_count,
            event_count         = event_count,
            noise_count         = noise_count,
            cluster_count       = cluster_count,
            cluster_label       = c["label"],
            is_main             = c["is_main"],
            cluster_point_count = c["point_count"],
            convex_hull         = c["convex_hull"],
            ellipse             = c["ellipse"],
        )
        for c in result["clusters"]
    ]

    db.add_all(rows)
    db.commit()
