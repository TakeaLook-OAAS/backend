from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.database import get_db
from core.deps import get_current_user
from database.enums import CampaignStatus
import database.models as models, database.schemas as schemas

router = APIRouter()

@router.get(
    "/map",
    response_model=schemas.DeviceMapResponse,
    summary="메인 페이지 지도용 기기 위치 목록 (내 캠페인만, 로그인 필요)",
)
def get_device_map(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    메인 페이지 지도에 찍을 마커 목록을 반환합니다.
    로그인한 광고주 **본인**이 신청한 캠페인의 위치만 대상입니다.
    (다른 광고주가 같은 기기에 신청했더라도, 그 광고주의 RUNNING 여부는
     이 응답에 영향을 주지 않습니다 — 색상은 항상 "내 캠페인" 기준입니다.)

    색상: 내 캠페인 중 그 기기를 참조하는 것 중 RUNNING이 하나라도 있으면
          "active"(초록), 없으면 "pending"(노랑).
    """
    campaigns = (
        db.query(models.Campaign)
        .filter(models.Campaign.user_id == current_user.id)
        .filter(models.Campaign.addresses.isnot(None))
        .all()
    )

    device_has_running: dict[str, bool] = {}
    referenced_device_ids: set[str] = set()

    for c in campaigns:
        for addr_entry in (c.addresses or []):
            device_id = addr_entry.get("device_id")
            if not device_id:
                continue
            referenced_device_ids.add(device_id)
            if c.status == CampaignStatus.RUNNING:
                device_has_running[device_id] = True

    if not referenced_device_ids:
        return schemas.DeviceMapResponse(markers=[])

    devices = (
        db.query(models.Device)
        .filter(models.Device.id.in_(referenced_device_ids))
        .filter(models.Device.latitude.isnot(None), models.Device.longitude.isnot(None))
        .all()
    )

    markers = [
        schemas.DeviceMapMarker(
            device_id = str(d.id),
            name      = d.name,
            address   = d.address or "",
            latitude  = d.latitude,
            longitude = d.longitude,
            status    = "active" if device_has_running.get(str(d.id)) else "pending",
        )
        for d in devices
    ]

    return schemas.DeviceMapResponse(markers=markers)


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