from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
import models, schemas

router = APIRouter()


@router.get("/", response_model=schemas.CampaignListResponse, summary="캠페인 목록 조회")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(models.Campaign).order_by(models.Campaign.created_at.desc()).all()
    results = []
    for c in campaigns:
        devices = [
            schemas.DeviceSimple(id=str(dc.device.id), name=dc.device.name, status=dc.device.status)
            for dc in c.device_campaigns
        ]
        results.append(schemas.CampaignWithDevices(
            id=str(c.id),
            name=c.name,
            status=c.status,
            start_date=c.start_date,
            end_date=c.end_date,
            devices=devices,
        ))
    return schemas.CampaignListResponse(results=results, total=len(results))
