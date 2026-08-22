from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import requests
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, override_settings

from apps.maps.exceptions import (
    CopernicusAuthenticationError,
    RasterProcessingError,
    SatelliteProcessRejected,
    SatelliteProcessUnavailable,
)
from apps.maps.services.copernicus import CopernicusScene
from apps.maps.services.sentinel_hub import (
    SENTINEL_BANDS_EVALSCRIPT,
    SentinelHubProcessClient,
    build_process_request,
)


class FakeResponse:
    def __init__(self, *, status=200, chunks=(), headers=None, stream_error=None):
        self.status_code = status
        self._chunks = chunks
        self.headers = headers or {"Content-Type": "image/tiff"}
        self.stream_error = stream_error
        self.closed = False

    def iter_content(self, chunk_size):
        if self.stream_error:
            raise self.stream_error
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeTokenProvider:
    def __init__(self, tokens=("token",)):
        self.tokens = iter(tokens)
        self.invalidated = 0

    def get_access_token(self):
        return next(self.tokens)

    def invalidate(self):
        self.invalidated += 1


@override_settings(
    COPERNICUS_PROCESS_URL="https://sh.example.test/process/v1",
    COPERNICUS_PROCESS_TIMEOUT_SECONDS=120,
    COPERNICUS_OUTPUT_RESOLUTION_METERS=10,
    COPERNICUS_MAX_OUTPUT_PIXELS=1_000_000,
    COPERNICUS_MAX_DOWNLOAD_BYTES=1024,
    COPERNICUS_SCENE_TIME_TOLERANCE_SECONDS=300,
)
class SentinelHubProcessClientTests(SimpleTestCase):
    def setUp(self):
        polygon = Polygon(
            (
                (-48.001, -15.001),
                (-48.001, -15.000),
                (-48.000, -15.000),
                (-48.000, -15.001),
                (-48.001, -15.001),
            ),
            srid=4326,
        )
        self.geometry = MultiPolygon(polygon, srid=4326)
        self.scene = CopernicusScene(
            item_id="sentinel-scene-123",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )

    def test_builds_projected_request_for_selected_scene(self):
        payload, grid = build_process_request(
            scene=self.scene,
            geometry=self.geometry,
            max_cloud_cover=Decimal("20"),
        )

        self.assertEqual(grid.epsg, 32722)
        self.assertGreater(grid.pixel_count, 0)
        bounds = payload["input"]["bounds"]
        self.assertEqual(bounds["geometry"]["type"], "MultiPolygon")
        self.assertEqual(
            bounds["properties"]["crs"],
            "http://www.opengis.net/def/crs/EPSG/0/32722",
        )
        data = payload["input"]["data"][0]
        self.assertEqual(data["type"], "sentinel-2-l2a")
        self.assertEqual(data["dataFilter"]["mosaickingOrder"], "leastCC")
        self.assertEqual(data["dataFilter"]["maxCloudCoverage"], 20.0)
        self.assertEqual(payload["output"]["resx"], 10)
        self.assertEqual(payload["evalscript"], SENTINEL_BANDS_EVALSCRIPT)
        # The window brackets the whole UTC day of acquisition (plus the
        # configured tolerance as padding), not a narrow band around the
        # exact timestamp: STAC and Sentinel Hub's own catalog can disagree
        # on the acquisition time by more than a few minutes.
        self.assertIn("2026-07-19T23:55:00Z", data["dataFilter"]["timeRange"]["from"])
        self.assertTrue(
            data["dataFilter"]["timeRange"]["to"].startswith("2026-07-21T00:04:59")
        )

    @override_settings(COPERNICUS_MAX_OUTPUT_PIXELS=1)
    def test_rejects_request_over_pixel_limit_before_network(self):
        with self.assertRaises(RasterProcessingError):
            build_process_request(
                scene=self.scene,
                geometry=self.geometry,
                max_cloud_cover=20,
            )

    def test_streams_tiff_to_target_and_closes_response(self):
        response = FakeResponse(
            chunks=(b"TIFF", b"-DATA"),
            headers={"Content-Type": "image/tiff", "Content-Length": "9"},
        )
        session = Mock()
        session.post.return_value = response
        client = SentinelHubProcessClient(
            session=session,
            token_provider=FakeTokenProvider(),
        )

        with TemporaryDirectory() as temporary_directory:
            downloaded = client.download_bands(
                scene=self.scene,
                geometry=self.geometry,
                max_cloud_cover=20,
                target_directory=Path(temporary_directory),
            )
            self.assertEqual(downloaded.path.read_bytes(), b"TIFF-DATA")
            self.assertEqual(downloaded.size_bytes, 9)
            self.assertFalse(
                (Path(temporary_directory) / "sentinel-input.tif.part").exists()
            )

        self.assertTrue(response.closed)
        request_headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(request_headers["Authorization"], "Bearer token")
        self.assertNotIn("oauth-secret", str(session.post.call_args))

    def test_refreshes_token_once_after_unauthorized_process_response(self):
        unauthorized = FakeResponse(status=401)
        success = FakeResponse(chunks=(b"TIFF",))
        session = Mock()
        session.post.side_effect = [unauthorized, success]
        provider = FakeTokenProvider(tokens=("expired", "fresh"))
        client = SentinelHubProcessClient(session=session, token_provider=provider)

        with TemporaryDirectory() as temporary_directory:
            client.download_bands(
                scene=self.scene,
                geometry=self.geometry,
                max_cloud_cover=20,
                target_directory=Path(temporary_directory),
            )

        self.assertEqual(provider.invalidated, 1)
        self.assertEqual(session.post.call_count, 2)
        self.assertTrue(unauthorized.closed)

    def test_classifies_process_errors_and_cleans_partial_file(self):
        cases = (
            (FakeResponse(status=403), CopernicusAuthenticationError),
            (FakeResponse(status=429), SatelliteProcessUnavailable),
            (FakeResponse(status=400), SatelliteProcessRejected),
            (
                FakeResponse(stream_error=requests.ConnectionError("broken stream")),
                SatelliteProcessUnavailable,
            ),
            (
                FakeResponse(chunks=(b"x" * 1025,)),
                SatelliteProcessRejected,
            ),
            (
                FakeResponse(headers={"Content-Length": "invalid"}),
                SatelliteProcessRejected,
            ),
        )
        for response, expected_exception in cases:
            with self.subTest(expected_exception=expected_exception):
                session = Mock()
                session.post.return_value = response
                client = SentinelHubProcessClient(
                    session=session,
                    token_provider=FakeTokenProvider(tokens=("first", "second")),
                )
                with TemporaryDirectory() as temporary_directory:
                    target = Path(temporary_directory)
                    with self.assertRaises(expected_exception):
                        client.download_bands(
                            scene=self.scene,
                            geometry=self.geometry,
                            max_cloud_cover=20,
                            target_directory=target,
                        )
                    self.assertFalse((target / "sentinel-input.tif.part").exists())
