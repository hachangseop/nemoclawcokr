"""FastAPI 앱. 인증은 DEV 모드(X-User-Email 헤더, 없으면 자동 생성).
Google OAuth 실연동 전까지의 개발용 방식임을 명시한다."""
import hashlib
import json
import logging
import os
import secrets

from fastapi import FastAPI, Depends, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db, init_db
from . import models, credits as credit_engine, queue as job_queue, billing
from .providers.fal import get_provider

log = logging.getLogger(__name__)
DEV_AUTH = os.environ.get("DEV_AUTH", "1") == "1"

app = FastAPI(title="AI Video SaaS Core", version="0.1.0")

# Lovable 등 별도 오리진 프론트에서 호출하므로 CORS 허용.
# 운영에서는 CORS_ORIGINS에 실제 프론트 도메인만 지정.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    init_db()
    # Render 무료 티어처럼 프로세스 1개만 되는 환경 대응:
    # 워커를 API 프로세스 안의 데몬 스레드로 함께 기동.
    # RUN_WORKER=0 이면 끄고 별도 프로세스(python -m app.worker)로 실행.
    if os.environ.get("RUN_WORKER", "1") == "1":
        import threading
        from .worker import main as worker_main
        t = threading.Thread(target=worker_main, daemon=True, name="job-worker")
        t.start()
        log.info("in-process job worker started")


def get_user(email: str | None, db: Session) -> models.User:
    if not DEV_AUTH:
        raise HTTPException(401, "Google OAuth not configured (set DEV_AUTH=1 for dev)")
    if not email:
        raise HTTPException(401, "X-User-Email header required in dev mode")
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        user = models.User(email=email, name=email.split("@")[0])
        db.add(user)
        db.commit()
        db.refresh(user)
        credit_engine.earn(db, user.id, 100, "signup_bonus")
    return user


def current_user(x_user_email: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> models.User:
    return get_user(x_user_email, db)


class EstimateReq(BaseModel):
    kind: str
    params: dict = {}


class JobReq(BaseModel):
    kind: str
    params: dict = {}


@app.get("/health")
def health():
    return {"ok": True, "dev_auth": DEV_AUTH,
            "provider": "fal" if os.environ.get("FAL_API_KEY") else "stub"}


@app.post("/api/v1/estimate")
def estimate(req: EstimateReq, user: models.User = Depends(current_user)):
    est = get_provider().estimate(req.kind, req.params)
    return {"kind": req.kind, "credits": est.credits, "eta_seconds": est.eta_seconds}


@app.post("/api/v1/jobs", status_code=201)
def create_job(req: JobReq, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    est = get_provider().estimate(req.kind, req.params)
    try:
        credit_engine.spend(db, user.id, est.credits, "job_spend")
    except credit_engine.InsufficientCredits as e:
        raise HTTPException(402, str(e))
    job = job_queue.enqueue(db, user.id, req.kind, json.dumps(req.params), est.credits)
    return {"id": job.id, "status": job.status, "credits_reserved": est.credits,
            "balance": credit_engine.balance(db, user.id)}


@app.get("/api/v1/jobs")
def list_jobs(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    jobs = db.query(models.Job).filter(models.Job.user_id == user.id).order_by(
        models.Job.id.desc()).limit(50).all()
    return [{"id": j.id, "kind": j.kind, "status": j.status,
             "output_url": j.output_url, "error": j.error,
             "created_at": j.created_at.isoformat() if j.created_at else None,
             "params": json.loads(j.params_json or "{}")} for j in jobs]



@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: int, user: models.User = Depends(current_user),
            db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "job not found")
    return {"id": job.id, "kind": job.kind, "status": job.status,
            "output_url": job.output_url, "error": job.error,
            "credits_charged": job.credits_charged,
            "params": json.loads(job.params_json or "{}")}
	


@app.get("/api/v1/credits/balance")
def balance(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return {"balance": credit_engine.balance(db, user.id)}


class TopUpReq(BaseModel):
    email: str
    amount: int


@app.post("/api/v1/admin/topup")
def admin_topup(req: TopUpReq, db: Session = Depends(get_db)):
    """개발용 크레딧 지급. 운영에서는 제거 또는 관리자 인증 필요."""
    if not DEV_AUTH:
        raise HTTPException(403, "disabled")
    user = get_user(req.email, db)
    credit_engine.earn(db, user.id, req.amount, "admin_grant")
    return {"email": req.email, "balance": credit_engine.balance(db, user.id)}


class ApiKeyReq(BaseModel):
    name: str = "default"


@app.post("/api/v1/apikeys", status_code=201)
def create_apikey(req: ApiKeyReq, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    raw = "sk_" + secrets.token_urlsafe(32)
    rec = models.ApiKey(user_id=user.id, key_prefix=raw[:11],
                        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                        name=req.name)
    db.add(rec)
    db.commit()
    return {"prefix": rec.key_prefix, "key": raw,
            "warning": "키를 지금 복사해둬. 다시 볼 수 없어."}


@app.get("/api/v1/apikeys")
def list_apikeys(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    keys = db.query(models.ApiKey).filter(models.ApiKey.user_id == user.id).all()
    return [{"prefix": k.key_prefix, "name": k.name, "revoked": bool(k.revoked),
             "created_at": k.created_at.isoformat() if k.created_at else None} for k in keys]


@app.post("/api/v1/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    secret = billing.webhook_secret()
    if secret:
        sig = request.headers.get("Stripe-Signature", "")
        if not billing.verify_stripe_signature(payload, sig, secret):
            raise HTTPException(400, "bad signature")
    else:
        log.warning("STRIPE_WEBHOOK_SECRET 미설정 — 개발 모드로 통과")
    try:
        event = json.loads(payload)
    except Exception:
        raise HTTPException(400, "bad json")
    result = billing.handle_event(db, event)
    return {"ok": True, "result": result}
