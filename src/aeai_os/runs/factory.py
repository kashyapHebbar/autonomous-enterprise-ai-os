from __future__ import annotations

from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import AppSettings, get_settings


def build_run_repository(settings: AppSettings | None = None):
    settings = settings or get_settings()
    backend = settings.run_repository_backend.strip().lower()
    if backend in {"memory", "in-memory", "in_memory"}:
        return InMemoryRunRepository()
    if backend == "sqlalchemy":
        from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository

        return SQLAlchemyRunRepository.from_url(
            settings.database_url,
            create_schema=settings.run_repository_create_schema,
        )
    raise ValueError(f"Unsupported run repository backend: {settings.run_repository_backend}")
