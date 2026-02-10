# MindHome - db.py | see version.py for version info
"""
Database session management with context manager.
No more manual session.close() - prevents session leaks.
"""

from contextlib import contextmanager
from sqlalchemy.orm import sessionmaker
from models import get_engine

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
