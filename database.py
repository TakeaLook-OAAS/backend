from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base  # Base는 models.py에 있음
import database

# PostgreSQL 연결 주소
# postgresql://계정명:비밀번호@주소:포트/DB이름
DB_URL = "postgresql://admin01:admin01@localhost/OAAS_DB"

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