"""DB 모델: 사용자·크레딧 원장·구독·API키·작업."""
import datetime
import enum
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255))
    google_sub = Column(String(255), unique=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CreditLedger(Base):
    """크레딧 원장. delta>0 적립, delta<0 차감. 잔액 = SUM(delta)."""
    __tablename__ = "credit_ledger"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    delta = Column(Integer, nullable=False)
    reason = Column(String(64), nullable=False)  # signup_bonus|purchase|subscription_grant|job_spend|refund|admin_grant
    ref_id = Column(String(64))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    stripe_subscription_id = Column(String(128), unique=True)
    plan = Column(String(64), nullable=False)
    status = Column(String(32), default="active")
    current_period_end = Column(DateTime)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    key_prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False)
    name = Column(String(128))
    revoked = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    kind = Column(String(64), nullable=False)  # 예: "video:kling", "image:flux"
    params_json = Column(Text, default="{}")
    status = Column(String(32), default=JobStatus.QUEUED.value, index=True)
    credits_reserved = Column(Integer, default=0)
    credits_charged = Column(Integer, default=0)
    output_url = Column(Text)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                       onupdate=datetime.datetime.utcnow)
