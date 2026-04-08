# api/v1/endpoints/export.py

import uuid
import csv
import io
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from database import get_db
import models

router = APIRouter()


@router.get(
    "/events/",
    summary="events_raw CSV 다운로드",
    description="기간과 캠페인 기준으로 events_raw를 CSV 파일로 다운로드합니다.",
)
def export_events_csv(
    campaign_id: uuid.UUID,
    start_date:  date,
    end_date:    date,
    device_id:   Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
):
    # 날짜 유효성 확인
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date는 start_date 이후여야 합니다.")

    query = (
        db.query(models.EventRaw)
        .filter(
            models.EventRaw.campaign_id == campaign_id,
            func.date(func.timezone('UTC', models.EventRaw.ts)) >= start_date,
            func.date(func.timezone('UTC', models.EventRaw.ts)) <= end_date,
        )
    )

    if device_id:
        query = query.filter(models.EventRaw.device_id == device_id)

    rows = query.order_by(models.EventRaw.ts.asc()).all()

    if not rows:
        raise HTTPException(status_code=404, detail="해당 조건의 데이터가 없습니다.")

    # CSV 생성
    output = io.StringIO()
    writer = csv.writer(output)

    # 헤더
    writer.writerow([
        "id", "ts", "device_id", "campaign_id", "track_id",
        "exposure_start_ms", "exposure_end_ms", "exposure_ms",
        "total_look_duration_ms", "age_group", "gender",
    ])

    # 데이터 행
    for row in rows:
        writer.writerow([
            str(row.id),
            row.ts.isoformat(),
            str(row.device_id),
            str(row.campaign_id),
            row.track_id,
            row.exposure_start_ms,
            row.exposure_end_ms,
            row.exposure_ms,
            row.total_look_duration_ms,
            row.age_group or "",
            row.gender or "",
        ])

    output.seek(0)

    filename = f"events_{start_date}_{end_date}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )