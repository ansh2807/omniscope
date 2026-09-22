from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """Add columns introduced after first install (create_all will not alter)."""
    patches = {
        "job": [
            ("recipient_email", "VARCHAR"),
            ("email_status", "VARCHAR"),
        ],
        "report": [
            ("summary_json", "TEXT"),
            ("fit_score", "FLOAT"),
            ("media_verdict", "VARCHAR"),
            ("subjects_json", "TEXT"),
        ],
        "entity": [
            ("watched", "BOOLEAN"),
            ("watch_json", "TEXT"),
        ],
    }
    inspector = inspect(engine)
    try:
        tables = set(inspector.get_table_names())
    except Exception:
        return
    with engine.begin() as conn:
        for table, cols in patches.items():
            if table not in tables:
                continue
            try:
                existing = {c["name"] for c in inspect(engine).get_columns(table)}
            except Exception:
                continue
            for name, coltype in cols:
                if name in existing:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"))
                except Exception:
                    pass


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
