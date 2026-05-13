from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database.database import get_db
from database.models import User
from database.schemas import UserResponse
from core.deps import get_current_admin

router = APIRouter()


@router.get("/users", response_model=List[UserResponse])
def list_users(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == str(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")
    if str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="자기 자신은 삭제할 수 없습니다.")
    db.delete(user)
    db.commit()


@router.patch("/users/{user_id}/suspend", response_model=UserResponse)
def suspend_user(user_id: str, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == str(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저를 찾을 수 없습니다.")
    if str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="자기 자신은 정지할 수 없습니다.")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return user
