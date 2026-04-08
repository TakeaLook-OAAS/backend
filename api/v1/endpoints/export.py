import uuid
import csv
import io
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
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

    # KST 기준 datetime 범위로 변환 (시스템 기준시 KST)
    KST = timezone(timedelta(hours=9))
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=KST)
    end_dt   = datetime(end_date.year,   end_date.month,   end_date.day,   tzinfo=KST) + timedelta(days=1)

    query = (
        db.query(models.EventRaw)
        .filter(
            models.EventRaw.campaign_id == campaign_id,
            models.EventRaw.ts >= start_dt,
            models.EventRaw.ts <  end_dt,
        )
    )

    if device_id:
        query = query.filter(models.EventRaw.device_id == device_id)

    query = query.order_by(models.EventRaw.ts.asc())

    # 데이터 존재 여부 먼저 확인
    if not db.query(query.exists()).scalar():
        raise HTTPException(status_code=404, detail="해당 조건의 데이터가 없습니다.")

    def generate():
        # 헤더
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "ts", "device_id", "campaign_id", "track_id",
            "exposure_start_ms", "exposure_end_ms", "exposure_ms",
            "total_look_duration_ms", "age_group", "gender",
        ])
        yield output.getvalue()

        # 1000행씩 청크 스트리밍
        for row in query.yield_per(1000):
            output = io.StringIO()
            writer = csv.writer(output)
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
                (row.age_group or "").replace("-", "~"),  # Excel 날짜 자동변환 방지 (10-19 → 10~19)
                row.gender or "",
            ])
            yield output.getvalue()

    filename = f"events_{start_date}_{end_date}.csv"

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )