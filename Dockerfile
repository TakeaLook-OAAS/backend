# 1. 베이스 이미지 선택 (팀원 모두 동일한 파이썬 버전 사용)
FROM python:3.11-slim

# 2. 컨테이너 내 작업 디렉토리 생성
WORKDIR /app

# 3. 호스트의 requirements.txt를 컨테이너로 복사
COPY requirements.txt .

# 4. 의존성 설치 (라이브러리 환경 통일)
# --no-cache-dir로 이미지 용량을 줄이고 깨끗한 상태 유지
RUN pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 복사
COPY . .

# 6. 실행 명령 (모두 동일한 포트와 설정으로 실행)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]