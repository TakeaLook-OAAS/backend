from fastapi import FastAPI
from api.v1.endpoints import events
from database import create_tables

app = FastAPI(title = "OAAS - Offline Ad Analysis Service")

@app.on_event("startup")
def startup() :
    create_tables()

# 라우터 등록
# events 파일 안의 정의된 모든 API를 포함시킴
app.include_router(events.router, prefix="/events", tags=["events"])

# 서버가 살아있는지 확인하는 API
@app.get("/")
def read_root() :
    return {"message": "OAAS 서버 정상 작동 중"}
