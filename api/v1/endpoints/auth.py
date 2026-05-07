import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from database import get_db
from models import User, RevokedToken, EmailVerification
from schemas import TokenResponse, UserCreate, UserResponse, SendCodeRequest, LoginRequest
from core.security import hash_password, verify_password, create_access_token, decode_access_token
from core.deps import get_current_user, oauth2_scheme
from core.email import send_verification_email
from enums import UserRole

router = APIRouter()


@router.post("/send-code", status_code=status.HTTP_200_OK)
def send_code(body: SendCodeRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 사용 중인 이메일입니다.")

    code = f"{random.randint(0, 999999):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    db.add(EmailVerification(email=body.email, code=code, expires_at=expires_at))
    db.commit()

    send_verification_email(body.email, code)
    return {"message": "인증 코드가 발송되었습니다."}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 사용 중인 이메일입니다.")

    now = datetime.now(timezone.utc)
    verification = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.email   == body.email,
            EmailVerification.code    == body.code,
            EmailVerification.is_used == False,
            EmailVerification.expires_at > now,
        )
        .order_by(EmailVerification.id.desc())
        .first()
    )
    if not verification:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="인증 코드가 올바르지 않거나 만료되었습니다.")

    verification.is_used = True
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        role=UserRole.USER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="비활성화된 계정입니다.")

    token = create_access_token({"sub": user.email, "role": user.role.value})
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(token)
        jti = payload.get("jti")
        if jti:
            db.add(RevokedToken(jti=jti))
            db.commit()
    except JWTError:
        pass
    return {"message": "로그아웃 되었습니다."}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
