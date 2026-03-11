from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db 

# APIRouter : API들을 묶어서 관리하기
router = APIRouter()

"""
AI 로그 데이터를 받는 POST 엔드포인트
URL은 main.py에서 prefix="/events" 로 미리 지정했음
원본 데이터를 수신하는 API
- data : 수신된 JSON 데이터
""" 
@router.post("/")
def creat_event(data: dict, db: Session = Depends(get_db)):
    print(f"수신된 데이터: {data}")
    return {"status": "success", 
            # 수신 확인 메세지는 테스트용으로 사용 후 주석처리 할 것
            "message": "데이터가 수신 완료",
            "received": data}