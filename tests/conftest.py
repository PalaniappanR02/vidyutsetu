import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.db import database

database.DATABASE_URL = os.environ["DATABASE_URL"]
database.engine = create_engine(
    database.DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
database.SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=database.engine,
)


@pytest.fixture(scope="session", autouse=True)
def fresh_database():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    yield
    database.engine.dispose()
