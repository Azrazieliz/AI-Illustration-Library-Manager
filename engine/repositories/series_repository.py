from __future__ import annotations

from engine.database.models.series import Series
from engine.repositories.base_repository import BaseRepository


class SeriesRepository(BaseRepository[Series]):
    """Repository for series persistence operations."""

    def __init__(self) -> None:
        super().__init__(Series)

    def create_series(self, *, name: str) -> Series:
        series = Series(name=name)
        self.add(series)
        self.commit()
        return series

    def get_series(self, identifier: int) -> Series | None:
        return self.get_by_id(identifier)

    def rename_series(self, series: Series, new_name: str) -> Series:
        series.name = new_name
        self.commit()
        return series

    def merge_series(self, source: Series, target: Series) -> Series:
        for image in source.images:
            image.series_id = target.id
        self.delete(source)
        self.commit()
        return target

    def list_series(self) -> list[Series]:
        return list(self.session.query(Series).order_by(Series.name).all())
