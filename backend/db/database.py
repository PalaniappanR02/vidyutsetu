"""SQLAlchemy Database Models and Session Configuration for VidyutSetu."""

import json
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, event
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

from backend.config import settings

DATABASE_URL = settings.database_url

_connect_args = {"check_same_thread": False, "timeout": settings.sqlite_busy_timeout_ms / 1000}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
        if DATABASE_URL not in {"sqlite://", "sqlite:///:memory:"}:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DBTestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint("total_score >= 0 AND total_score <= 100", name="ck_test_runs_total_score"),
    )

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
    __table_args__ = (Index("ix_meter_history_meter_id_id", "meter_id", "id"),)

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
    __table_args__ = (
        ForeignKeyConstraint(["suite_id"], ["test_suites.id"], ondelete="CASCADE"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    suite_id = Column(Integer, nullable=False, index=True)
    run_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    results_json = Column(Text, nullable=False, default="[]")
    passed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)


class DBUser(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'operator', 'viewer')", name="ck_users_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_login_at = Column(DateTime, nullable=True)


class DBAuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class DBLoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_address_time", "address_hash", "attempted_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    address_hash = Column(String(64), nullable=False)
    attempted_at = Column(DateTime, nullable=False, index=True)


class DBAuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_type_outcome", "event_type", "outcome"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(128), nullable=False)
    outcome = Column(String(16), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


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


def _ensure_suite_run_foreign_key() -> None:
    """Rebuild legacy SQLite suite_runs tables without dropping their stored rows."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "suite_runs" not in inspector.get_table_names():
        return
    foreign_keys = inspector.get_foreign_keys("suite_runs")
    if any(
        key.get("constrained_columns") == ["suite_id"]
        and key.get("referred_table") == "test_suites"
        for key in foreign_keys
    ):
        return

    with engine.begin() as connection:
        orphan = connection.execute(
            text(
                "SELECT suite_runs.id FROM suite_runs "
                "LEFT JOIN test_suites ON test_suites.id = suite_runs.suite_id "
                "WHERE test_suites.id IS NULL LIMIT 1"
            )
        ).first()
        if orphan is not None:
            raise RuntimeError(
                "Cannot add the suite_runs foreign key while orphaned suite runs exist"
            )
        connection.execute(
            text(
                "CREATE TABLE suite_runs_migrating ("
                "id INTEGER PRIMARY KEY, "
                "suite_id INTEGER NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE, "
                "run_at DATETIME, "
                "results_json TEXT NOT NULL DEFAULT '[]', "
                "passed_count INTEGER NOT NULL DEFAULT 0, "
                "failed_count INTEGER NOT NULL DEFAULT 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO suite_runs_migrating "
                "(id, suite_id, run_at, results_json, passed_count, failed_count) "
                "SELECT id, suite_id, run_at, results_json, passed_count, failed_count "
                "FROM suite_runs"
            )
        )
        connection.execute(text("DROP TABLE suite_runs"))
        connection.execute(
            text("ALTER TABLE suite_runs_migrating RENAME TO suite_runs")
        )


def _ensure_metadata_indexes() -> None:
    """Create indexes missing from databases created before their ORM definitions."""
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_test_run_columns()
    _ensure_suite_run_foreign_key()
    _ensure_metadata_indexes()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
