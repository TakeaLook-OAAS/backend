# 📊 오프라인 광고 시청자 몰입도 분석 서비스 (Backend)

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

> **AI 비전 기술을 활용한 오프라인 광고판 시청자 분석 및 통계 제공 API 서버** <br>
> 대용량 트래픽 처리를 위한 마이크로 배치 아키텍처 적용

## 💡 프로젝트 소개
오프라인 매장에 설치된 카메라(Device)를 통해 수집된 AI 비전 데이터를 처리하고, 광고 캠페인별 시청자의 몰입도(Attention)와 체류 시간(Dwell Time)을 분석하여 통계를 제공하는 백엔드 시스템입니다.

## 🏗️ 시스템 아키텍처 (System Architecture)
- **Multi-Repo 연동:** AI Vision (Data Source) -> Backend (API/DB) -> Frontend (Dashboard)
- **DB 설계:** SQLAlchemy 기반의 7개 핵심 테이블 (유저, 기기, 구역, 캠페인, 원본 로그, 시/일별 통계)

## 🛠️ 기술 스택 (Tech Stack)
- **Framework:** FastAPI (Python 3.x)
- **Database:** PostgreSQL (SQLAlchemy ORM)
- **Infrastructure:** Docker, Docker-compose

## 🚀 시작하기 (Getting Started)

### 1. 프로젝트 클론
\`\`\`bash
git clone https://github.com/TakeaLook/OAAS/backend.git
cd backend
\`\`\`

### 2. Docker를 이용한 DB 및 서버 실행
\`\`\`bash
docker-compose up -d
\`\`\`

## 📚 API 문서 (API Documentation)
FastAPI가 제공하는 자동 생성 문서를 통해 API 명세를 확인할 수 있습니다.
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

## 👨‍💻 팀원 (Team)
- **Backend:** [전민형/https://github.com/kchhq]
- **AI Vision:** [권준성], [정현석], [장수정]
- **Frontend:** [박장우]
