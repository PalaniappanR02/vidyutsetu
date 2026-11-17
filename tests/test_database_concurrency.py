from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend.db import database


def test_sqlite_accepts_concurrent_independent_run_writes(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={
            "check_same_thread": False,
            "timeout": database.settings.sqlite_busy_timeout_ms / 1000,
        },
    )
    event.listen(engine, "connect", database._configure_sqlite_connection)
    database.Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    writers = 8
    start = Barrier(writers)

    def write_run(index):
        with sessions() as session:
            start.wait(timeout=10)
            session.add(
                database.DBTestRun(
                    run_id=f"RUN-CONCURRENT-{index}",
                    source_vendor="delta-legacy",
                )
            )
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=writers) as executor:
            list(executor.map(write_run, range(writers)))
        with sessions() as session:
            count = session.scalar(
                select(func.count()).select_from(database.DBTestRun)
            )
        assert count == writers
    finally:
        engine.dispose()
