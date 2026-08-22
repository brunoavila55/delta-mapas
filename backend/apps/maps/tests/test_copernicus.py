from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, override_settings

from apps.maps.exceptions import NoSatelliteSceneFound, SatelliteCatalogError
from apps.maps.services.copernicus import CopernicusSceneService


FULL_TILE_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [
        [
            (-49.0, -16.0),
            (-49.0, -14.0),
            (-47.0, -14.0),
            (-47.0, -16.0),
            (-49.0, -16.0),
        ]
    ],
}


def make_item(
    item_id: str,
    *,
    acquired_at: datetime,
    cloud_cover: object,
    asset_names: tuple[str, ...] = ("B04_10m", "B08_10m", "SCL_20m"),
    geometry: dict | None = FULL_TILE_GEOMETRY,
):
    return SimpleNamespace(
        id=item_id,
        datetime=acquired_at,
        collection_id="sentinel-2-l2a",
        properties={"eo:cloud_cover": cloud_cover, "platform": "sentinel-2c"},
        assets={
            name: SimpleNamespace(href=f"https://example.test/{item_id}/{name}.jp2")
            for name in asset_names
        },
        geometry=geometry,
    )


@override_settings(
    COPERNICUS_STAC_URL="https://stac.example.test/v1/",
    COPERNICUS_STAC_COLLECTION="sentinel-2-l2a",
    COPERNICUS_STAC_TIMEOUT_SECONDS=12,
    COPERNICUS_STAC_MAX_ITEMS=25,
)
class CopernicusSceneServiceTests(SimpleTestCase):
    def setUp(self):
        polygon = Polygon(
            (
                (-48.01, -15.01),
                (-48.01, -15.00),
                (-48.00, -15.00),
                (-48.00, -15.01),
                (-48.01, -15.01),
            ),
            srid=4326,
        )
        self.geometry = MultiPolygon(polygon, srid=4326)

    def service_with_items(self, items):
        search = Mock()
        search.items.return_value = iter(items)
        client = Mock()
        client.search.return_value = search
        factory = Mock(return_value=client)
        return CopernicusSceneService(client_factory=factory), factory, client

    def test_selects_lowest_cloud_cover_then_most_recent_scene(self):
        items = [
            make_item(
                "cloudy",
                acquired_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
                cloud_cover=12,
            ),
            make_item(
                "best-older",
                acquired_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                cloud_cover="2.5",
            ),
            make_item(
                "best-newer",
                acquired_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                cloud_cover=Decimal("2.5"),
            ),
        ]
        service, factory, client = self.service_with_items(items)

        scene = service.search_best_scene(
            geometry=self.geometry,
            requested_scene_date=None,
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31),
            max_cloud_cover=Decimal("20"),
        )

        self.assertEqual(scene.item_id, "best-newer")
        self.assertEqual(scene.cloud_cover, Decimal("2.5"))
        self.assertEqual(set(scene.assets), {"B04", "B08", "SCL"})
        factory.assert_called_once_with("https://stac.example.test/v1/", timeout=12)
        search_kwargs = client.search.call_args.kwargs
        self.assertEqual(search_kwargs["collections"], ["sentinel-2-l2a"])
        self.assertEqual(search_kwargs["max_items"], 25)
        self.assertEqual(search_kwargs["query"], {"eo:cloud_cover": {"lte": 20.0}})
        self.assertEqual(
            search_kwargs["sortby"],
            "+properties.eo:cloud_cover,-properties.datetime,+id",
        )
        self.assertEqual(search_kwargs["intersects"]["type"], "MultiPolygon")
        start, end = search_kwargs["datetime"]
        self.assertEqual(start, datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(end.date(), date(2026, 7, 31))

    def test_specific_date_search_covers_the_complete_utc_day(self):
        service, _, client = self.service_with_items(
            [
                make_item(
                    "same-day",
                    acquired_at=datetime(2026, 7, 7, 13, tzinfo=timezone.utc),
                    cloud_cover=1,
                )
            ]
        )

        service.search_best_scene(
            geometry=self.geometry,
            requested_scene_date=date(2026, 7, 7),
            date_from=None,
            date_to=None,
            max_cloud_cover=Decimal("10"),
        )

        start, end = client.search.call_args.kwargs["datetime"]
        self.assertEqual(start.date(), date(2026, 7, 7))
        self.assertEqual(end.date(), date(2026, 7, 7))
        self.assertLess(start, end)

    def test_discards_items_over_limit_or_without_required_assets(self):
        items = [
            make_item(
                "over-limit",
                acquired_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                cloud_cover=21,
            ),
            make_item(
                "missing-scl",
                acquired_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                cloud_cover=1,
                asset_names=("B04_10m", "B08_10m"),
            ),
        ]
        service, _, _ = self.service_with_items(items)

        with self.assertRaises(NoSatelliteSceneFound):
            service.search_best_scene(
                geometry=self.geometry,
                requested_scene_date=None,
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 31),
                max_cloud_cover=Decimal("20"),
            )

    def test_discards_items_that_do_not_fully_cover_the_area(self):
        partial_overlap_geometry = {
            "type": "Polygon",
            "coordinates": [
                [
                    (-48.015, -15.015),
                    (-48.015, -15.005),
                    (-48.005, -15.005),
                    (-48.005, -15.015),
                    (-48.015, -15.015),
                ]
            ],
        }
        items = [
            make_item(
                "partial-coverage",
                acquired_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
                cloud_cover=1,
                geometry=partial_overlap_geometry,
            ),
            make_item(
                "no-geometry",
                acquired_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
                cloud_cover=1,
                geometry=None,
            ),
        ]
        service, _, _ = self.service_with_items(items)

        with self.assertRaises(NoSatelliteSceneFound):
            service.search_best_scene(
                geometry=self.geometry,
                requested_scene_date=None,
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 31),
                max_cloud_cover=Decimal("20"),
            )

    def test_wraps_catalog_transport_errors(self):
        service = CopernicusSceneService(
            client_factory=Mock(side_effect=TimeoutError("catalog timeout"))
        )

        with self.assertRaises(SatelliteCatalogError):
            service.search_best_scene(
                geometry=self.geometry,
                requested_scene_date=date(2026, 7, 7),
                date_from=None,
                date_to=None,
                max_cloud_cover=Decimal("20"),
            )
