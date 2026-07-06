from __future__ import annotations

from engine.database.models.series import Series
from engine.services.base_service import BaseService


class SeriesService(BaseService[Series]):
    """Service layer for series entities."""

    def create_series(self, *, name: str) -> Series:
        series = Series(name=name)
        self.add(series)
        self.commit()
        return series

    def get_series(self, identifier: int) -> Series | None:
        return self.get_by_id(Series, identifier)

    def rename_series(self, series: Series, new_name: str) -> Series:
        series.name = new_name
        self.commit()
        return series

    def merge_series(self, source: Series, target: Series) -> Series:
        for image in source.images:
            image.series_id = target.id
        self.session.delete(source)
        self.commit()
        return target

    def list_series(self) -> list[Series]:
        return list(self.session.query(Series).order_by(Series.name).all())
