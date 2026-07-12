from __future__ import annotations

import shutil
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings

_alembic_lock = threading.RLock()


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def make_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        sqlite_url(path),
        connect_args={"check_same_thread": False, "timeout": 5},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def run_migrations(path: Path, scope: str, *, backup: bool = False) -> None:
    # Alembic's EnvironmentContext uses module-level proxies and is not safe to
    # run concurrently, even when separate SQLite files are being migrated.
    with _alembic_lock:
        if backup and path.exists() and path.stat().st_size:
            backup_path = path.with_suffix(f".{scope}-migration.bak")
            shutil.copy2(path, backup_path)
        config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
        config = Config(str(config_path))
        config.set_main_option("script_location", str(config_path.parent / "migrations" / scope))
        config.set_main_option("sqlalchemy.url", sqlite_url(path))
        command.upgrade(config, "head")


class DatabaseManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.projects_dir.mkdir(parents=True, exist_ok=True)
        run_migrations(settings.catalog_path, "catalog")
        self.catalog_engine = make_engine(settings.catalog_path)
        self.catalog_factory = sessionmaker(self.catalog_engine, expire_on_commit=False)
        self._project_engines: dict[str, Engine] = {}
        self._project_factories: dict[str, sessionmaker[Session]] = {}
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

    @contextmanager
    def catalog(self) -> Iterator[Session]:
        session = self.catalog_factory()
        try:
            yield session
        finally:
            session.close()

    def project_db_path(self, folder_path: str | Path) -> Path:
        return Path(folder_path).resolve() / "story.db"

    def ensure_project_database(self, project_id: str, folder_path: str | Path) -> None:
        with self._locks[project_id]:
            if project_id in self._project_engines:
                return
            path = self.project_db_path(folder_path)
            run_migrations(path, "project", backup=path.exists())
            engine = make_engine(path)
            self._project_engines[project_id] = engine
            self._project_factories[project_id] = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def project(self, project_id: str, folder_path: str | Path) -> Iterator[Session]:
        self.ensure_project_database(project_id, folder_path)
        session = self._project_factories[project_id]()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def project_write(self, project_id: str, folder_path: str | Path) -> Iterator[Session]:
        with self._locks[project_id]:
            with self.project(project_id, folder_path) as session:
                with session.begin():
                    yield session

    def dispose(self) -> None:
        self.catalog_engine.dispose()
        for engine in self._project_engines.values():
            engine.dispose()
