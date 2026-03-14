"""
Database connection and session management
"""
import os
import logging
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from backend.database.models import Base

logger = logging.getLogger(__name__)

# Load environment
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / '.env')

# Database URL from environment or default to SQLite
_default_db_path = Path.home() / '.ln-escrow' / 'escrow.db'
DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///{_default_db_path.absolute()}")

# Ensure directory exists for SQLite
if DATABASE_URL.startswith('sqlite:///'):
    db_path = Path(DATABASE_URL.replace('sqlite:///', ''))
    db_path.parent.mkdir(parents=True, exist_ok=True)

# Create engine
_is_sqlite = DATABASE_URL.startswith('sqlite')
engine = create_engine(
    DATABASE_URL,
    echo=os.getenv('DATABASE_ECHO', 'false').lower() == 'true',
    # SQLite specific settings
    connect_args={'check_same_thread': False} if _is_sqlite else {}
)

# SQLite: enable WAL mode (concurrent readers + single writer) and busy_timeout
# (wait up to 5s for lock instead of failing immediately with "database is locked")
if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")  # Safe with WAL
        cursor.close()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database — run Alembic migrations, fall back to create_all."""
    _run_migrations()


def _run_migrations():
    """Run Alembic migrations to bring the DB up to date."""
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.migration import MigrationContext

        # Check if alembic_version table exists (i.e. DB is already stamped)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        alembic_cfg = Config(str(Path(__file__).parent.parent.parent / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

        if current_rev is None:
            # First time: check if tables already exist (pre-Alembic DB)
            from sqlalchemy import inspect
            inspector = inspect(engine)
            if 'deals' in inspector.get_table_names():
                # Existing DB without Alembic tracking — stamp it at head
                logger.info("Existing database detected — stamping Alembic at head")
                command.stamp(alembic_cfg, "head")
            else:
                # Fresh install — run all migrations
                logger.info("Fresh database — running Alembic migrations")
                command.upgrade(alembic_cfg, "head")
        else:
            # Already tracked — apply any pending migrations
            logger.info("Running pending Alembic migrations (current: %s)", current_rev)
            command.upgrade(alembic_cfg, "head")

    except Exception as e:
        logger.warning("Alembic migration failed (%s), falling back to create_all", e)
        Base.metadata.create_all(bind=engine)


@contextmanager
def get_db_session():
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_tables():
    """Ensure tables exist (call on startup) — uses Alembic migrations."""
    _run_migrations()
