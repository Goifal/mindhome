# MindHome - db.py | see version.py for version info
"""
Database session management with context manager.
No more manual session.close() - prevents session leaks.
"""

import logging
import time
from contextlib import contextmanager
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from models import get_engine

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory = None


def init_db(engine=None):
    """Initialize the database module with an engine."""
    global _engine, _SessionFactory
    _engine = engine or get_engine()
    _SessionFactory = sessionmaker(bind=_engine)
    return _engine


def get_engine_instance():
    """Get the current engine instance."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def get_db():
    """Get a new database session (legacy compatibility).
    IMPORTANT: Caller must close the session manually.
    Prefer using get_db_session() context manager instead.
    """
    global _SessionFactory, _engine
    if _SessionFactory is None:
        init_db()
    return _SessionFactory()


@contextmanager
def get_db_session():
    """Context manager for safe database sessions.

    Usage:
        with get_db_session() as session:
            user = session.query(User).first()
            # session auto-commits on success, auto-rollbacks on error
            # session auto-closes when exiting the block
    """
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_db_readonly():
    """Context manager for read-only database access.
    No commit is called - slightly faster for pure reads.
    """
    global _SessionFactory
    if _SessionFactory is None:
        init_db()
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()


def db_write_with_retry(func, retries=3):
    """Execute a write operation with retry on 'database is locked'.

    Args:
        func: Callable that receives a session and performs DB writes.
              The session is committed automatically on success.
        retries: Number of attempts (default 3).

    Returns:
        The return value of func.

    Usage:
        def do_insert(session):
            session.add(MyModel(name="test"))
            return {"success": True}

        result = db_write_with_retry(do_insert)
    """
    global _SessionFactory
    if _SessionFactory is None:
        init_db()

    last_err = None
    for attempt in range(retries):
        session = _SessionFactory()
        try:
            result = func(session)
            session.commit()
            return result
        except OperationalError as e:
            session.rollback()
            if "database is locked" in str(e) and attempt < retries - 1:
                logger.warning("DB locked (attempt %d/%d), retrying...",
                               attempt + 1, retries)
                last_err = e
                time.sleep(1.0 * (attempt + 1))
            else:
                raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    raise last_err
