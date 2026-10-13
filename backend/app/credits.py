"""크레딧 엔진. 잔액 = 원장 합계. 차감 전 잔액 확인, 부족하면 거부."""
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models


class InsufficientCredits(Exception):
    pass


def balance(db: Session, user_id: int) -> int:
    total = db.query(func.coalesce(func.sum(models.CreditLedger.delta), 0)).filter(
        models.CreditLedger.user_id == user_id
    ).scalar()
    return int(total)


def earn(db: Session, user_id: int, amount: int, reason: str, ref_id: str = None) -> None:
    assert amount > 0, "earn amount must be positive"
    db.add(models.CreditLedger(user_id=user_id, delta=amount, reason=reason, ref_id=ref_id))
    db.commit()


def spend(db: Session, user_id: int, amount: int, reason: str, ref_id: str = None) -> None:
    assert amount > 0, "spend amount must be positive"
    if balance(db, user_id) < amount:
        raise InsufficientCredits(f"need {amount}, have {balance(db, user_id)}")
    db.add(models.CreditLedger(user_id=user_id, delta=-amount, reason=reason, ref_id=ref_id))
    db.commit()
