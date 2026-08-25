from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database.models import Base  # Base는 models.py에 있음
import os
import logging

logger = logging.getLogger(__name__)

# 환경변수에서 DB 접속 정보 읽기
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME")

DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# create_engine()의 괄호 안 = PostgreSQL 연결 주소
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# DB에 테이블 생성하는 함수
def create_tables():
    Base.metadata.create_all(bind=engine)
    _upgrade_existing_schema()


def _upgrade_existing_schema():
    """
    Base.metadata.create_all()은 '테이블이 아예 없을 때만' 생성하고,
    이미 존재하는 테이블에는 새로 추가된 컬럼을 반영하지 않는다.
    Alembic 같은 정식 마이그레이션 도구가 없는 상태이므로,
    자주 누락되는 컬럼 추가만 여기서 방어적으로(이미 있으면 무시) 보정한다.

    운영 DB는 보통 수동 ALTER TABLE로 먼저 반영하지만, 로컬/신규 환경에서
    이 단계가 빠졌을 때 devices.address 등 컬럼이 없어 500이 나는 걸 방지한다.
    """
    statements = [
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS address VARCHAR(255) UNIQUE",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS latitude FLOAT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS longitude FLOAT",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # 스키마 보정 실패로 서버 기동 자체를 막지는 않음 — 로그만 남기고 계속 진행
                logger.warning(f"[schema-upgrade] 실행 실패 (무시하고 계속): {stmt} | {e}")

# DB 세션 가져오기
def get_db():
    db = SessionLocal()
    try :
        yield db
    finally :
        db.close()

if __name__ == "__main__":
    create_tables()
    print("모든 테이블이 성공적으로 생성되었습니다")