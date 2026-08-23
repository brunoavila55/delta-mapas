from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import requests
from django.conf import settings
from pystac_client import Client
from pystac_client.exceptions import APIError
from pystac_client.stac_api_io import StacApiIO

from ..exceptions import NoSatelliteSceneFound, SatelliteCatalogError

REQUIRED_ASSET_ALIASES: dict[str, tuple[str, ...]] = {
    "B04": ("B04_10m", "B04"),
    "B08": ("B08_10m", "B08"),
    "SCL": ("SCL_20m", "SCL"),
}


class BoundedStacApiIO(StacApiIO):
    def __init__(self, *, timeout: float) -> None:
        super().__init__(timeout=timeout, max_retries=0)
        self._remaining_bytes = settings.COPERNICUS_STAC_MAX_TOTAL_BYTES

    def request(self, href, method=None, headers=None, parameters=None):
        request_method = method or "GET"
        kwargs: dict[str, object] = {
            "headers": headers,
            "timeout": self.timeout,
            "stream": True,
            "allow_redirects": False,
        }
        if request_method == "POST":
            kwargs["json"] = parameters
        else:
            kwargs["params"] = parameters
        try:
            response = self.session.request(request_method, href, **kwargs)
        except requests.RequestException as exc:
            raise APIError(str(exc)) from exc
        try:
            if response.status_code != 200:
                raise APIError(f"STAC API returned HTTP {response.status_code}.")
            page_limit = settings.COPERNICUS_STAC_MAX_RESPONSE_BYTES
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_bytes = int(content_length)
                except ValueError as exc:
                    raise APIError(
                        "STAC API returned an invalid Content-Length."
                    ) from exc
                if declared_bytes < 0 or declared_bytes > page_limit:
                    raise APIError("STAC API response exceeds the per-page limit.")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > page_limit:
                    raise APIError("STAC API response exceeds the per-page limit.")
                if len(body) > self._remaining_bytes:
                    raise APIError("STAC API responses exceed the aggregate limit.")
            self._remaining_bytes -= len(body)
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise APIError("STAC API response is not valid UTF-8.") from exc
        finally:
            response.close()


@dataclass(frozen=True, slots=True)
class CopernicusScene:
    item_id: str
    acquired_at: datetime
    cloud_cover: Decimal
    assets: dict[str, str]
    collection: str
    platform: str | None


def _utc_day_interval(selected_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(selected_date, time.min, tzinfo=timezone.utc),
        datetime.combine(selected_date, time.max, tzinfo=timezone.utc),
    )


def _search_interval(
    *,
    requested_scene_date: date | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime, datetime]:
    if requested_scene_date:
        return _utc_day_interval(requested_scene_date)
    if date_from and date_to:
        return (
            datetime.combine(date_from, time.min, tzinfo=timezone.utc),
            datetime.combine(date_to, time.max, tzinfo=timezone.utc),
        )
    raise ValueError("A complete scene date or date range is required.")


def _cloud_cover(item: Any) -> Decimal | None:
    raw_value = item.properties.get("eo:cloud_cover")
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def _required_assets(item: Any) -> dict[str, str] | None:
    resolved: dict[str, str] = {}
    for logical_name, aliases in REQUIRED_ASSET_ALIASES.items():
        for alias in aliases:
            asset = item.assets.get(alias)
            href = getattr(asset, "href", "") if asset else ""
            if href:
                resolved[logical_name] = href
                break
        else:
            return None
    return resolved


class CopernicusSceneService:
    def __init__(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.client_factory = client_factory

    def search_best_scene(
        self,
        *,
        geometry,
        requested_scene_date: date | None,
        date_from: date | None,
        date_to: date | None,
        max_cloud_cover: Decimal,
    ) -> CopernicusScene:
        interval = _search_interval(
            requested_scene_date=requested_scene_date,
            date_from=date_from,
            date_to=date_to,
        )
        intersects = json.loads(geometry.geojson)

        try:
            if self.client_factory is None:
                timeout = settings.COPERNICUS_STAC_TIMEOUT_SECONDS
                client = Client.open(
                    settings.COPERNICUS_STAC_URL,
                    timeout=timeout,
                    stac_io=BoundedStacApiIO(timeout=timeout),
                )
            else:
                client = self.client_factory(
                    settings.COPERNICUS_STAC_URL,
                    timeout=settings.COPERNICUS_STAC_TIMEOUT_SECONDS,
                )
            search = client.search(
                collections=[settings.COPERNICUS_STAC_COLLECTION],
                intersects=intersects,
                datetime=interval,
                query={"eo:cloud_cover": {"lte": float(max_cloud_cover)}},
                sortby="+properties.eo:cloud_cover,-properties.datetime,+id",
                max_items=settings.COPERNICUS_STAC_MAX_ITEMS,
            )
            items = list(search.items())
        except Exception as exc:
            raise SatelliteCatalogError(
                "Não foi possível consultar o catálogo de imagens."
            ) from exc

        candidates: list[CopernicusScene] = []
        for item in items:
            cloud_cover = _cloud_cover(item)
            acquired_at = item.datetime
            assets = _required_assets(item)
            if (
                cloud_cover is None
                or cloud_cover > max_cloud_cover
                or acquired_at is None
                or assets is None
            ):
                continue
            if acquired_at.tzinfo is None:
                acquired_at = acquired_at.replace(tzinfo=timezone.utc)
            candidates.append(
                CopernicusScene(
                    item_id=item.id,
                    acquired_at=acquired_at,
                    cloud_cover=cloud_cover,
                    assets=assets,
                    collection=item.collection_id
                    or settings.COPERNICUS_STAC_COLLECTION,
                    platform=item.properties.get("platform"),
                )
            )

        if not candidates:
            raise NoSatelliteSceneFound(
                "Nenhuma cena compatível foi encontrada para a área e período."
            )

        candidates.sort(
            key=lambda scene: (
                scene.cloud_cover,
                -scene.acquired_at.timestamp(),
                scene.item_id,
            )
        )
        return candidates[0]
