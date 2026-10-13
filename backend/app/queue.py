"""DB 기반 작업 큐. Redis 없이 동작. 워커가 claim → 실행 → 완료/실패."""
import datetime
from sqlalchemy.orm import Session
from . import models


def enqueue(db: Session, user_id: int, kind: str, params_json: str, credits_reserved: int) -> models.Job:
    job = models.Job(
        user_id=user_id, kind=kind, params_json=params_json,
        status=models.JobStatus.QUEUED.value, credits_reserved=credits_reserved,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def claim_next(db: Session) -> models.Job | None:
    job = (
        db.query(models.Job)
        .filter(models.Job.status == models.JobStatus.QUEUED.value)
        .order_by(models.Job.id.asc())
        .first()
    )
    if not job:
        return None
    job.status = models.JobStatus.RUNNING.value
    job.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job_id: int, output_url: str, credits_charged: int) -> None:
    job = db.get(models.Job, job_id)
    job.status = models.JobStatus.SUCCEEDED.value
    job.output_url = output_url
    job.credits_charged = credits_charged
    job.updated_at = datetime.datetime.utcnow()
    db.commit()


def fail(db: Session, job_id: int, error: str) -> None:
    job = db.get(models.Job, job_id)
    job.status = models.JobStatus.FAILED.value
    job.error = error[:2000]
    job.updated_at = datetime.datetime.utcnow()
    db.commit()
