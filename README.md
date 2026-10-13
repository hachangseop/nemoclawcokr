# AI Video SaaS — Phase 1 (Backend Core)

RunningHub.ai 분석(REA, ~/workspace/rea/runninghub/ANALYSIS.md)을 바탕으로 재구현하는
AI 영상 생성 SaaS의 백엔드 코어.

## 아키텍처
- FastAPI + SQLAlchemy (기본 SQLite, `DATABASE_URL`로 Postgres 교체)
- DB 기반 작업 큐 + 워커 (Redis 없이 동작, 나중에 Redis 어댑터 교체 가능)
- 크레딧 원장(복식 기록): 적립/차감/환불 전 이력 보존
- 실행 프로바이더 인터페이스: FAL.AI / Replicate (키 없으면 StubProvider로 시뮬레이션)
- Stripe 웹훅 스켈레톤 (서명 검증 포함), Google OAuth는 스텁

## 실행
```
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000      # API
python -m app.worker                  # 워커 (별도 프로세스)
```

## Phase 구분
- Phase 1 (여기): 백엔드 코어 — 작업 실행·크레딧·구독·API키
- Phase 2: Lovable 프론트 빌드 스펙 (docs/lovable-spec.md 예정)
- Phase 3: Cloudflare 배포 (사용자)
