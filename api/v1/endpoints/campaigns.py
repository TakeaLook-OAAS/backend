from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.database import get_db
from core.deps import get_current_user
import database.models as models, database.schemas as schemas

router = APIRouter()


@router.post("/", response_model=schemas.CampaignWithDevices, summary="캠페인 생성", status_code=201)
def create_campaign(
    campaign_in:  schemas.CampaignCreate,
    db:           Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    if campaign_in.end_date < campaign_in.start_date:
        raise HTTPException(status_code=400, detail="end_date는 start_date보다 작을 수 없습니다.")

    campaign = models.Campaign(
        user_id          = current_user.id,
        name             = campaign_in.name,
        start_date       = campaign_in.start_date,
        end_date         = campaign_in.end_date,
        target_age_group = campaign_in.target_age_group,
        target_gender    = campaign_in.target_gender,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return schemas.CampaignWithDevices(
        id         = str(campaign.id),
        name       = campaign.name,
        status     = campaign.status,
        start_date = campaign.start_date,
        end_date   = campaign.end_date,
        devices    = [],
    )


@router.get("/", response_model=schemas.CampaignListResponse, summary="캠페인 목록 조회")
def list_campaigns(
    db:           Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    campaigns = (
        db.query(models.Campaign)
        .filter(models.Campaign.user_id == current_user.id)
        .order_by(models.Campaign.created_at.desc())
        .all()
    )
    results = []
    for c in campaigns:
        devices = [
            schemas.DeviceSimple(id=str(dc.device.id), name=dc.device.name, status=dc.device.status)
            for dc in c.device_campaigns
        ]
        results.append(schemas.CampaignWithDevices(
            id         = str(c.id),
            name       = c.name,
            status     = c.status,
            start_date = c.start_date,
            end_date   = c.end_date,
            devices    = devices,
        ))
    return schemas.CampaignListResponse(results=results, total=len(results))