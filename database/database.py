from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base  # Base는 models.py에 있음
import os

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