"""SQLAlchemy Database Models and Session Configuration for VidyutSetu."""

import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine,
    inspect,
    text,
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./vidyutsetu.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DBTestRun(Base):
    __tablename__ = "test_runs"

    run_id = Column(String(64), primary_key=True, index=True)
    execution_time = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    source_vendor = Column(String(64), nullable=False)
    target_vendor = Column(String(64), nullable=True)
    total_records = Column(Integer, default=0)
    valid_records = Column(Integer, default=0)
    invalid_records = Column(Integer, default=0)
    syntactic_score = Column(Float, default=100.0)
    semantic_score = Column(Float, default=100.0)
    integrity_score = Column(Float, default=100.0)
    total_score = Column(Float, default=100.0)
    grade = Column(String(8), default="A+")
    summary = Column(Text, default="")
    issues_json = Column(Text, default="[]")
    raw_preview = Column(Text, default="")
    canonical_preview = Column(Text, default="")
    target_preview = Column(Text, default="")
    duration_ms = Column(Float, default=0.0)
    # Additive run metadata (Batch A): safe for rows written before these existed.
    model_version = Column(String(64), nullable=True)
    data_quality_score = Column(Float, nullable=True)


class DBCustomVendorConfig(Base):
    __tablename__ = "custom_vendor_configs"

    vendor_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    system_type = Column(String(32), default="HES")
    format_type = Column(String(32), default="json")
    protocol = Column(String(64), default="CUSTOM")
    config_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBMeterHistory(Base):
    __tablename__ = "meter_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meter_id = Column(String(128), nullable=False, index=True)
    ts = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)


class DBTestSuite(Base):
    __tablename__ = "test_suites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    scenarios_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBSuiteRun(Base):
    __tablename__ = "suite_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    suite_id = Column(Integer, nullable=False, index=True)
    run_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    results_json = Column(Text, nullable=False, default="[]")
    passed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)


ADDITIVE_TEST_RUN_COLUMNS = {
    "model_version": "VARCHAR(64)",
    "data_quality_score": "FLOAT",
}


def _add_missing_test_run_columns() -> None:
    """Add Batch A columns to a pre-existing test_runs table, keeping all rows."""
    inspector = inspect(engine)
    if "test_runs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("test_runs")}
    missing = {
        name: ddl
        for name, ddl in ADDITIVE_TEST_RUN_COLUMNS.items()
        if name not in existing
    }
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing.items():
            connection.execute(text(f"ALTER TABLE test_runs ADD COLUMN {name} {ddl}"))


def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_test_run_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
