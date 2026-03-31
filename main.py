from fastapi import FastAPI
from sqlalchemy import text
from api.v1.endpoints import events
from database import create_tables, get_db

app = FastAPI(title = "OAAS - Offline Ad Analysis Service")

@app.on_event("startup")
def startup() :
    create_tables()

# 라우터 등록
# events 파일 안에 정의된 모든 API를 포함시킴
app.include_router(events.router, prefix="/events", tags=["events"])


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def read_root():
    """기본 헬스체크 — 서버가 살아있는지 확인합니다."""
    return {"status": "ok", "message": "OAAS 서버 정상 작동 중"}


@app.get("/health", tags=["health"])
def health_check():
    """
    상세 헬스체크 API — AI 기기에서 서버 상태를 확인할 때 사용합니다.
    - DB 연결 상태까지 포함해 반환합니다.
    - DB 연결 실패 시 503 대신 db_ok=false로 표시해 서버 자체는 응답합니다.
    """
    db_ok = False
    # DB 연결 확인 — 간단한 쿼리로 연결 상태 점검
    try:
        db = next(get_db())
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "db":     "connected" if db_ok else "disconnected",
    }
