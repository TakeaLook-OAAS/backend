# OAAS 백엔드 문서
> Offline Ad Analysis Service — 오프라인 광고 효율 분석 서비스

---

## 목차
1. [프로젝트 개요](#1-프로젝트-개요)
2. [폴더 구조](#2-폴더-구조)
3. [데이터 흐름도](#3-데이터-흐름도)
4. [DB 테이블 설명](#4-db-테이블-설명)
5. [API 엔드포인트](#5-api-엔드포인트)

---

## 1. 프로젝트 개요

오프라인 광고판 옆에 설치된 AI 기기가 광고판 앞을 지나가는 사람들을 분석하고, 그 결과를 백엔드 서버로 전송합니다. 백엔드는 이 데이터를 수집·집계하여 관리자와 광고주가 대시보드에서 광고 효율을 확인할 수 있도록 제공합니다.

**담당 범위 (백엔드)**
```
AI팀 → [수신 API] → events_raw 저장
                          ↓
               [집계 스케줄러 - 자정]
                          ↓
          daily_aggs / hourly_aggs 저장
                          ↓
              [조회 API] → 프론트엔드
```

**기술 스택**

| 항목 | 내용 |
|------|------|
| Framework | FastAPI (Python 3.10+) |
| Database | PostgreSQL 15 (Docker) |
| ORM | SQLAlchemy 2.0 |
| Validation | Pydantic V2 |
| 스케줄러 | APScheduler (자정 집계) |
| 실행 환경 | venv + Docker (PostgreSQL) |

---

## 2. 폴더 구조

```
GRADUATEMISSION/
│
├── api/
│   └── v1/
│       ├── endpoints/
│       │   ├── devices.py       # 기기 관련 API
│       │   ├── events.py        # AI팀 데이터 수신 API (핵심)
│       │   └── users.py         # 유저 관련 API
│       └── api_v1.py            # v1 라우터 통합
│
├── Aggregation.py               # 집계 로직 (daily_aggs / hourly_aggs)
├── database.py                  # DB 연결 및 세션 관리
├── enums.py                     # Enum 정의 (DeviceStatus, CampaignStatus, UserRole)
├── main.py                      # FastAPI 앱 진입점, 테이블 자동 생성
├── models.py                    # SQLAlchemy DB 모델 정의
├── schemas.py                   # Pydantic 요청/응답 스키마
├── docker-compose.yml           # PostgreSQL 컨테이너 설정
├── requirements.txt             # Python 패키지 목록
└── README.md
```

---

## 3. 데이터 흐름도

### 3-1. 데이터 수신 흐름

```
[AI 기기]
  - 광고판 앞 인물 추적 (10분 단위 배치)
  - track 완료된 데이터 모아서 전송
        ↓ POST /events/
[FastAPI - events.py]
  - UUID 유효성 검사
  - tracks 배열을 1행씩 풀어서 저장
        ↓ db.add_all()
[PostgreSQL - events_raw]
  - track 1개 = 1행
  - ingested_at 자동 기록 (서버 수신 시각)
```

### 3-2. 집계 흐름

```
[APScheduler]
  - 매일 자정 00:00 자동 실행
        ↓
[Aggregation.py]
  - events_raw에서 전날 데이터 조회
  - 지표 계산:
      · exposure_count  (총 노출 인구)
      · interested_count (관심 인구 — look_times 있는 사람)
      · attention_rate  (관심도 = 관심인구 / 총노출인구)
      · 나이대별 인원 (10대~50대이상)
      · 성별 인원 (male / female)
        ↓
[PostgreSQL - daily_aggs / hourly_aggs]
```

### 3-3. 조회 흐름

```
[프론트엔드]
  - 대시보드에서 캠페인별 통계 요청
        ↓ GET /stats/daily  or  GET /stats/hourly
[FastAPI]
  - daily_aggs / hourly_aggs 조회
        ↓
[프론트엔드]
  - 총 노출 인구, 관심도, 나이대/성별 분포 시각화
```

### 3-4. 시간 보정

AI 기기는 절대 시각 없이 ms 단위 상대 시간만 전송합니다.
서버 수신 시각(`ingested_at`)을 기준으로 실제 시각을 역산합니다.

```
실제 노출 시각 = ingested_at - max(exposure.end_ms) + exposure.start_ms
```

집계 시 `ingested_at`의 분(minute)이 배치 주기(10분) 이내이면 이전 시간대 버킷으로 보정합니다.

---

## 4. DB 테이블 설명

### users
로그인 유저 정보를 저장합니다. 관리자(ADMIN)와 광고주(USER)로 구분됩니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK, 자동 생성 |
| email | String | 로그인 ID, UNIQUE |
| hashed_password | String | bcrypt 해시된 비밀번호 |
| role | Enum | ADMIN / USER |
| is_active | Boolean | 회원탈퇴 시 False |
| created_at | DateTime | 생성 시간 |
| updated_at | DateTime | 수정 시간 |

---

### devices
광고판 옆에 설치된 AI 기기 정보를 저장합니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK, 자동 생성 |
| name | String(20) | 기기 이름, UNIQUE |
| status | Enum | ENABLE / DISABLE |
| timezone | String(32) | 설치 지역 타임존 (예: Asia/Seoul) |
| created_at | DateTime | 생성 시간 |

---

### rois (관심 구역)
기기가 촬영하는 화면 영역을 정의합니다.
현재 화면 전체를 ROI 1개로 사용하며, 기기 등록 시 자동 생성됩니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK, 자동 생성 |
| device_id | UUID | FK → devices.id |
| name | String(50) | ROI 이름 |
| polygon | JSONB | ROI 좌표 데이터 |
| created_at | DateTime | 생성 시간 |

> **제약조건**: 같은 기기 내 ROI 이름 중복 불가 (`uq_roi_device_name`)

---

### campaigns
광고 캠페인 정보를 저장합니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK, 자동 생성 |
| name | String(100) | 광고명 |
| start_date | Date | 광고 시작일 |
| end_date | Date | 광고 종료일 |
| status | Enum | DRAFT / RUNNING / PAUSED / ENDED |
| created_at | DateTime | 생성 시간 |
| updated_at | DateTime | 수정 시간 |

> **제약조건**: `end_date >= start_date`

---

### events_raw
AI 기기에서 수신한 원본 로그입니다. track 1개 = 1행으로 저장됩니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK, 자동 생성 |
| ingested_at | DateTime | 서버 수신 시각 (자동 기록) |
| device_id | UUID | FK → devices.id |
| campaign_id | UUID | FK → campaigns.id |
| track_id | Integer | AI팀 track 식별자 (배치 내 정수) |
| exposure_start_ms | Integer | 노출 시작 시각 (ms, 상대시간) |
| exposure_end_ms | Integer | 노출 종료 시각 (ms, 상대시간) |
| exposure_dwell_ms | Integer | 체류 시간 (ms) |
| look_times | JSONB | 시선 구간 목록 (원본 보존) |
| total_look_duration_ms | Integer | 총 시선 시간 (ms) |
| age_group | String(20) | 나이대 (nullable) |
| gender | String(10) | 성별 (nullable) |

> **제약조건**: `(device_id, track_id, ingested_at)` 조합 UNIQUE

**look_times JSONB 구조**
```json
[
  { "start_ms": 7631, "end_ms": 8589, "duration_ms": 958 },
  { "start_ms": 44493, "end_ms": 45192, "duration_ms": 699 }
]
```

---

### hourly_aggs
시간 단위 집계 결과입니다. 매일 자정 APScheduler가 생성합니다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BigInteger | PK, 자동 증가 |
| hour | DateTime | 집계 대상 시간 (예: 2026-03-10 14:00:00) |
| device_id | UUID | FK → devices.id |
| campaign_id | UUID | FK → campaigns.id |
| exposure_count | Integer | 총 노출 인구 |
| interested_count | Integer | 관심 인구 |
| attention_rate | Float | 관심도 (interested / exposure) |
| count_10s | Integer | 10대 인원 |
| count_20s | Integer | 20대 인원 |
| count_30s | Integer | 30대 인원 |
| count_40s | Integer | 40대 인원 |
| count_50s_plus | Integer | 50대 이상 인원 |
| count_male | Integer | 남성 인원 |
| count_female | Integer | 여성 인원 |
| created_at | DateTime | 생성 시간 |
| updated_at | DateTime | 수정 시간 |

> **제약조건**: `(hour, device_id, campaign_id)` 조합 UNIQUE

---

### daily_aggs
일 단위 집계 결과입니다. 컬럼 구조는 hourly_aggs와 동일하며 `hour` 대신 `date`(Date 타입)를 사용합니다.

> **제약조건**: `(date, device_id, campaign_id)` 조합 UNIQUE

---

## 5. API 엔드포인트

### POST /events/
AI팀 배치 데이터 수신 API입니다.

**요청 바디**
```json
{
  "device_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "campaign_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tracks": [
    {
      "track_id": 1,
      "exposure": {
        "start_ms": 222,
        "end_ms": 161292,
        "dwell_ms": 161070
      },
      "look_times": [
        { "start_ms": 7631, "end_ms": 8589, "duration_ms": 958 }
      ],
      "total_look_duration_ms": 42547,
      "age_group": "adult",
      "gender": "male"
    }
  ]
}
```

**응답**
```json
{
  "inserted": 1,
  "status": "success"
}
```

**처리 로직**
- `device_id`, `campaign_id` UUID 유효성 검사 → 실패 시 422 반환
- `tracks` 배열을 풀어 track 1개 → `events_raw` 1행으로 저장
- `ingested_at`은 서버가 자동 기록 (AI팀이 보내지 않음)
- DB 저장 실패 시 rollback 후 500 반환

---

### 기타 엔드포인트 (구현 예정)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /stats/daily | 일별 집계 조회 |
| GET | /stats/hourly | 시간별 집계 조회 |
| POST | /devices/ | 기기 등록 |
| POST | /users/register | 회원가입 |
| POST | /users/login | 로그인 |

---

## 실행 방법

```bash
# 1. Docker 실행 (PostgreSQL)
docker-compose up -d

# 2. 가상환경 활성화
source .venv/bin/activate  # macOS/Linux

# 3. FastAPI 실행 (테이블 자동 생성)
uvicorn main:app --reload

# 4. Swagger UI 접속
http://localhost:8000/docs
```

