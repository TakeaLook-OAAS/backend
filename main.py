from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from api.v1.endpoints import events, stats, auth, admin
from database import get_db, create_tables
from contextlib import asynccontextmanager
from api.v1.endpoints import export
import os

# -------------------------------------------------------------------
# [Lifespan 이벤트 핸들러 정의]
# 서버가 켜질 때와 꺼질 때의 작업을 하나의 함수에서 안전하게 관리합니다.
# -------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup (서버 시작 시점) ---
    # yield 구문 이전에 작성된 코드는 서버가 요청을 받기 전에 실행됩니다.
    # 예: DB 테이블 자동 생성 확인, 초기 데이터 로드 등
    print("앱 구동 시작: 필요한 초기화 작업을 수행합니다.")
    create_tables()
    
    yield  # 이 지점에서 서버가 구동되며 클라이언트의 요청을 받기 시작합니다.
    
    # --- Shutdown (서버 종료 시점) ---
    # yield 구문 이후에 작성된 코드는 서버가 꺼질 때 실행됩니다.
    # 예: 열려있는 DB 커넥션 풀 닫기, 임시 파일 삭제 등
    print("앱 구동 종료: 리소스를 안전하게 정리합니다.")

app = FastAPI(title="OAAS API", lifespan=lifespan)

origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
# events 파일 안에 정의된 모든 API를 포함시킴
app.include_router(auth.router,        prefix="/auth",        tags=["auth"])
app.include_router(events.router,      prefix="/events",      tags=["events"])
app.include_router(stats.router,       prefix="/stats",       tags=["stats"])
app.include_router(export.router,      prefix="/export",      tags=["export"])
app.include_router(admin.router,       prefix="/admin",       tags=["admin"])

# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def read_root():
    """기본 헬스체크 — 서버가 살아있는지 확인합니다."""
    return {"status": "ok", "message": "OAAS 서버 정상 작동 중"}

@app.get("/health", tags=["health"])
def health_check(db: Session = Depends(get_db)):
    """
    상세 헬스체크 API — AI 기기에서 서버 상태를 확인할 때 사용합니다.
    - DB 연결 상태까지 포함해 반환합니다.
    - DB 연결 실패 시 503 대신 db_ok=false로 표시해 서버 자체는 응답합니다.
    """
    db_ok = False
    # DB 연결 확인 — 간단한 쿼리로 연결 상태 점검
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "db":     "connected" if db_ok else "disconnected",
    }

