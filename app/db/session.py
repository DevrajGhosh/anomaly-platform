# app/db/session.py
"""
SQLAlchemy async engine + session factory.

Why async?
  FastAPI is async-first. Using an async DB driver (asyncpg) means DB calls
  never block the event loop — critical for real-time signal throughput.

Why a session factory?
  Each request gets its own session (connection) that is opened and closed
  cleanly, preventing connection leaks.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# ── Engine ─────────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # Logs SQL when DEBUG=True — very useful in dev
    pool_pre_ping=True,        # Tests connection health before use
    pool_size=10,              # Connection pool size
    max_overflow=20,           # Extra connections under load
)

# ── Session factory ────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,    # Don't expire objects after commit (safer for async)
    autocommit=False,
    autoflush=False,
)

# ── Base class for all ORM models ──────────────────────────────────────────
class Base(DeclarativeBase):
    """
    All SQLAlchemy ORM models inherit from this.
    Keeps metadata centralised for Alembic autogenerate.
    """
    pass


# ── Dependency for FastAPI routes ──────────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    FastAPI dependency that provides a DB session per request.
    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise