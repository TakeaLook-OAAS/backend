# 현재 로그인한 유저인지 판단하는 기능을 넣지 않았는데 수정할수있음
import logging
from fastapi import APIRouter, HTTPException
import database.schemas as schemas
from core.email import send_inquiry_email

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", status_code=202, summary="문의 접수")
def create_inquiry(inquiry: schemas.InquiryCreate):
    """사용자 문의를 관리자 이메일로 전송 (DB 저장 없음)"""
    try:
        send_inquiry_email(
            name=inquiry.name,
            email=inquiry.email,
            content=inquiry.content,
        )
    except Exception as e:
        logger.error(f"[Inquiry] 이메일 전송 실패 | {e}")
        raise HTTPException(status_code=500, detail="문의 전송에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    return {"message": "문의가 접수되었습니다."}

