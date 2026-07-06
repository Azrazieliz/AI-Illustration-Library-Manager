from __future__ import annotations

from engine.database.models.series import Series
from engine.repositories.series_repository import SeriesRepository
from engine.services.base_service import BaseService


class SeriesService(BaseService[Series]):
    """Service layer for series entities."""

    def __init__(self, repository: SeriesRepository | None = None) -> None:
        super().__init__(repository or SeriesRepository())
        self.repository = repository or SeriesRepository()

    def create_series(self, *, name: str) -> Series:
        return self.repository.create_series(name=name)

    def get_series(self, identifier: int) -> Series | None:
        return self.repository.get_series(identifier)

    def rename_series(self, series: Series, new_name: str) -> Series:
        return self.repository.rename_series(series, new_name)

    def merge_series(self, source: Series, target: Series) -> Series:
        return self.repository.merge_series(source, target)

    def list_series(self) -> list[Series]:
        return self.repository.list_series()
