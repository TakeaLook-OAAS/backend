from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from database.database import get_db
from database.models import ChangeRequest, Campaign, User
from database.schemas import ChangeRequestCreate, ChangeRequestResponse, ChangeRequestListResponse
from database.enums import ChangeRequestStatus
from core.deps import get_current_user, get_current_admin

router = APIRouter()


def _to_response(cr: ChangeRequest) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=str(cr.id),
        campaign_id=str(cr.campaign_id),
        campaign_name=cr.campaign.name,
        status=cr.status.value,
        target_gender=cr.target_gender,
        target_age_group=cr.target_age_group,
        start_date=cr.start_date,
        end_date=cr.end_date,
        broadcast_start=cr.broadcast_start,
        broadcast_end=cr.broadcast_end,
        reason=cr.reason,
        created_at=cr.created_at,
        reviewed_at=cr.reviewed_at,
    )


@router.post("/", response_model=ChangeRequestResponse, status_code=status.HTTP_201_CREATED)
def create_change_request(
    body: ChangeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign = db.query(Campaign).filter(Campaign.id == body.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")

    existing = db.query(ChangeRequest).filter(
        ChangeRequest.campaign_id == body.campaign_id,
        ChangeRequest.status == ChangeRequestStatus.PENDING,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 검토 중인 변경 요청이 있습니다.")

    cr = ChangeRequest(
        campaign_id=body.campaign_id,
        target_gender=body.target_gender,
        target_age_group=body.target_age_group,
        start_date=body.start_date,
        end_date=body.end_date,
        broadcast_start=body.broadcast_start,
        broadcast_end=body.broadcast_end,
        reason=body.reason,
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return _to_response(cr)


@router.get("/", response_model=ChangeRequestListResponse)
def list_change_requests(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(ChangeRequest).order_by(ChangeRequest.created_at.desc()).all()
    return ChangeRequestListResponse(results=[_to_response(r) for r in rows], total=len(rows))


@router.post("/{request_id}/approve", response_model=ChangeRequestResponse)
def approve_change_request(
    request_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
    if cr.status != ChangeRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="이미 처리된 요청입니다.")

    campaign = db.query(Campaign).filter(Campaign.id == cr.campaign_id).first()
    if cr.target_gender is not None:
        campaign.target_gender = cr.target_gender
    if cr.target_age_group is not None:
        campaign.target_age_group = cr.target_age_group
    if cr.start_date is not None:
        campaign.start_date = cr.start_date
    if cr.end_date is not None:
        campaign.end_date = cr.end_date

    cr.status = ChangeRequestStatus.APPROVED
    cr.reviewed_at = func.now()
    db.commit()
    db.refresh(cr)
    return _to_response(cr)


@router.post("/{request_id}/reject", response_model=ChangeRequestResponse)
def reject_change_request(
    request_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
    if cr.status != ChangeRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="이미 처리된 요청입니다.")

    cr.status = ChangeRequestStatus.REJECTED
    cr.reviewed_at = func.now()
    db.commit()
    db.refresh(cr)
    return _to_response(cr)
