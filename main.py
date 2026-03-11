from fastapi import FastAPI
from api.v1.endpoints import events

app = FastAPI(title = "OAAS - Offline Ad Analysis Service")

# docker-compose.yml의 설정과 맞춰야함
# postgresql://계정명:비밀번호@주소:포트/DB이름
# 지금은 여기에 두지만 나중엔 하드코딩 안하고 
DB_URL = "postgresql://admin01:admin01@localhost:5432/asdf_DB"

# 라우터 등록
# events 파일 안의 정의된 모든 API를 포함시킴
app.include_router(events.router, prefix="/events", tags=["events"])

# 서버가 살아있는지 확인하는 API
@app.get("/")
def read_root() :
    return {"message": "OAAS 서버 정상 작동 중"}
