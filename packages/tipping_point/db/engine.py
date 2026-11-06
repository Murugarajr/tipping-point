"""SQLAlchemy engine and session lifecycle for Tipping Point."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DatabaseConfig

config = DatabaseConfig()

engine = create_engine(
    config.database_url,
    pool_size=config.pool_size,
    max_overflow=config.max_overflow,
    pool_timeout=config.pool_timeout,
    pool_recycle=config.pool_recycle,
    pool_pre_ping=config.pool_pre_ping,
)


Base = declarative_base()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)
