# SubFlow

SaaS 벤더를 위한 **구독 관리 및 정산 플랫폼** REST API

## 프로젝트 소개

SubFlow는 SaaS 벤더가 구독 플랜을 등록하고, 유저가 구독·결제하며, 플랫폼이 벤더별 수수료를 자동 정산하는 전체 플로우를 구현한 백엔드 API입니다.

### 핵심 기능

- **역할 기반 접근 제어** — Admin / Vendor / User 3단계 권한 체계
- **구독 라이프사이클** — 생성 → 활성 → 만료/해지 자동 관리 (Celery Beat)
- **토스페이먼츠 결제 연동** — Gateway 패턴 모듈화, Webhook 수신, 결제 취소, 재시도 로직
- **3계층 정산 시스템** — SettlementRate(수수료율) → Settlement(벤더별 요약) → UserSettlement(유저별 상세)
- **정합성 검증** — 정산 전 예상값 사전 계산 → 실제 결과 비교 → SettlementHistory 감사 추적

## 기술 스택

| 분류 | 기술 |
|------|------|
| Language | Python 3.11 |
| Framework | Django 4.2, Django REST Framework |
| Database | PostgreSQL 15 |
| Task Queue | Celery + Redis |
| Auth | SimpleJWT (Access + Refresh Token) |
| API Docs | drf-spectacular (Swagger UI) |
| Container | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| Testing | pytest, pytest-django, pytest-cov |

## 아키텍처

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Client    │────▶│  Django API  │────▶│ PostgreSQL  │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────▼───────┐     ┌─────────────┐
                    │    Celery    │────▶│    Redis     │
                    │  Worker/Beat │     │  (Broker)   │
                    └──────────────┘     └─────────────┘
                           │
                    ┌──────▼───────┐
                    │ TossPayments │
                    │   Gateway    │
                    └──────────────┘
```

## 프로젝트 구조

```
subflow/
├── apps/
│   ├── accounts/       # 유저 모델, 회원가입, JWT 인증
│   ├── vendors/        # 벤더 등록, 승인, 수수료율 관리
│   ├── plans/          # 구독 플랜 CRUD (Starter/Pro/Enterprise)
│   ├── subscriptions/  # 구독 생성, 해지, 만료 자동 처리
│   ├── payments/       # 결제 생성, PG 승인, Webhook, 취소
│   ├── settlements/    # 3계층 정산, 정합성 검증, 실행 이력
│   └── common/         # 공통 권한 클래스
├── config/
│   ├── settings/       # base / local / production / test 분리
│   ├── celery.py       # Celery 설정
│   └── urls.py         # API 라우팅 (v1 prefix)
├── tests/              # pytest 기반 테스트
├── .github/workflows/  # GitHub Actions CI
├── docker-compose.yml  # 5개 서비스 (web, db, redis, worker, beat)
├── Dockerfile
└── requirements.txt
```

## 정산 시스템 상세

SubFlow의 정산은 3계층 구조로 설계되어 각 단계별 검증이 가능합니다.

```
SettlementRate (벤더별 수수료율)
    └── Settlement (벤더별 기간 정산 요약)
            └── UserSettlement (유저별 결제 건 상세)

SettlementHistory (실행 이력 — 정합성 검증 + 감사 추적)
```

**정산 실행 흐름:**

1. Admin이 정산 기간을 지정하여 실행 (Celery 비동기)
2. 승인된 벤더별로 해당 기간의 완료된 결제를 집계
3. SettlementRate에서 적용할 수수료율 조회 (없으면 벤더 기본값 사용)
4. 정산 전 예상값(벤더 수, 결제 건수)을 사전 계산
5. transaction.atomic() 내에서 Settlement + UserSettlement 생성
6. 예상값 vs 실제값 비교 → 정합성 검증
7. SettlementHistory에 실행 결과, 소요시간, 검증 결과 기록

## 실행 방법

### Docker Compose (권장)

```bash
# 1. 환경변수 설정
cp .env.example .env

# 2. 실행 (web, db, redis, celery worker, celery beat)
docker compose up -d

# 3. Swagger UI 확인
open http://localhost:8000/api/docs/
```

### 로컬 개발

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env

# 4. DB 마이그레이션
python manage.py migrate

# 5. 서버 실행
python manage.py runserver
```

### 테스트 실행

```bash
pytest -v --cov=apps --cov-report=term-missing
```

## API 엔드포인트

| Method | Endpoint | 설명 | 권한 |
|--------|----------|------|------|
| POST | `/api/v1/accounts/register/` | 회원가입 | 전체 |
| POST | `/api/v1/accounts/token/` | JWT 토큰 발급 | 전체 |
| POST | `/api/v1/vendors/register/` | 벤더 등록 신청 | Vendor |
| PATCH | `/api/v1/vendors/{id}/approve/` | 벤더 승인/거절 | Admin |
| GET/POST | `/api/v1/plans/` | 플랜 조회/생성 | Auth/Vendor |
| POST | `/api/v1/subscriptions/` | 구독 생성 | User |
| POST | `/api/v1/subscriptions/{id}/cancel/` | 구독 해지 | User |
| POST | `/api/v1/payments/create/` | 결제 요청 생성 | User |
| POST | `/api/v1/payments/confirm/` | 결제 승인 (PG) | Auth |
| POST | `/api/v1/payments/webhook/` | PG Webhook 수신 | 전체 |
| POST | `/api/v1/payments/{id}/cancel/` | 결제 취소 | User |
| GET | `/api/v1/settlements/` | 정산 목록 조회 | Admin/Vendor |
| POST | `/api/v1/settlements/generate/` | 정산 생성 (비동기) | Admin |
| POST | `/api/v1/settlements/{id}/complete/` | 정산 완료 처리 | Admin |
| GET | `/api/v1/settlements/history/` | 정산 실행 이력 | Admin |
| GET/POST | `/api/v1/settlements/rates/` | 정산율 조회/등록 | Admin |
| GET | `/api/docs/` | Swagger UI | 전체 |
