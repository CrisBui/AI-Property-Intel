from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from property_intel.config import get_settings
from property_intel.db.models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        connect_args: dict = {}
        engine_kwargs: dict = {}

        if settings.is_sqlite:
            db_path = settings.database_path_resolved
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connect_args["check_same_thread"] = False
        else:
            engine_kwargs.update(
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )

        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            **engine_kwargs,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

        if settings.is_sqlite:
            Base.metadata.create_all(_engine)
        else:
            sync_postgres_sequences(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Clear cached engine (useful after switching DATABASE_URL)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def sync_postgres_sequences(engine=None) -> None:
    """Align serial sequences with MAX(id) after bulk imports."""
    settings = get_settings()
    if settings.is_sqlite:
        return

    eng = engine or get_engine()
    with eng.connect() as conn:
        for table in ("raw_listings", "listings"):
            conn.execute(
                text(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE((SELECT MAX(id) FROM {table}), 1)
                    )
                    """
                )
            )
        conn.commit()


def reset_postgres_sequences(session: Session) -> None:
    """Sync serial sequences after bulk import with explicit ids."""
    settings = get_settings()
    if settings.is_sqlite:
        return

    for table in ("raw_listings", "listings"):
        session.execute(
            text(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1)
                )
                """
            )
        )
