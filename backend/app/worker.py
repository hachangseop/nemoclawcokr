"""워커: 큐에서 작업을 꺼내 프로바이더로 실행. 별도 프로세스로 기동.
    python -m app.worker
"""
import json
import logging
import time

from .db import SessionLocal, init_db
from . import queue as job_queue
from .providers.fal import get_provider

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_once() -> bool:
    db = SessionLocal()
    try:
        job = job_queue.claim_next(db)
        if not job:
            return False
        log.info("running job %s kind=%s", job.id, job.kind)
        try:
            out = get_provider().run(job.kind, json.loads(job.params_json or "{}"))
            job_queue.complete(db, job.id, out, job.credits_reserved)
            log.info("job %s done -> %s", job.id, out)
        except Exception as e:  # noqa: BLE001
            job_queue.fail(db, job.id, str(e))
            log.exception("job %s failed", job.id)
        return True
    finally:
        db.close()


def main(poll_seconds: float = 2.0):
    init_db()
    log.info("worker started (stub provider unless FAL_API_KEY set)")
    while True:
        if not run_once():
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
