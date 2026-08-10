from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context, tenant_context
from rest_framework.test import APIClient
from shapely.geometry import Polygon as ShapelyPolygon

from apps.accounts.models import Membership
from apps.properties.models import Property
from apps.tenants.models import Domain, Tenant


@override_settings(SECRET_KEY="test-secret-key-with-at-least-thirty-two-bytes")
class PropertyAPITests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de testes"
        return tenant

    @staticmethod
    def get_test_schema_name():
        return "test_properties"

    @staticmethod
    def get_test_tenant_domain():
        return "properties.test.localhost"

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="agronomo",
            email="agronomo@example.com",
            password="test-password-123",
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=Membership.Role.AGRONOMIST,
        )
        self.client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        self.client.force_authenticate(self.user)

    @staticmethod
    def polygon_geojson():
        return {
            "type": "Polygon",
            "coordinates": [
                [
                    [-48.01, -15.01],
                    [-48.01, -15.00],
                    [-48.00, -15.00],
                    [-48.00, -15.01],
                    [-48.01, -15.01],
                ]
            ],
        }

    def test_crud_normalizes_polygon_and_calculates_area(self):
        create_response = self.client.post(
            "/api/v1/properties/",
            {
                "name": "Fazenda Delta",
                "geometry": self.polygon_geojson(),
                "city": "Brasília",
                "state": "DF",
                "country": "br",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["geometry"]["type"], "MultiPolygon")
        self.assertGreater(float(create_response.data["area_hectares"]), 0)
        self.assertEqual(create_response.data["country"], "BR")

        property_id = create_response.data["id"]
        list_response = self.client.get("/api/v1/properties/?search=Delta")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)

        patch_response = self.client.patch(
            f"/api/v1/properties/{property_id}/",
            {"name": "Fazenda Delta Atualizada"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data["name"], "Fazenda Delta Atualizada")

        delete_response = self.client.delete(f"/api/v1/properties/{property_id}/")
        self.assertEqual(delete_response.status_code, 204)

    def test_non_polygon_geometry_is_rejected(self):
        response = self.client.post(
            "/api/v1/properties/",
            {
                "name": "Linha inválida",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-48.0, -15.0], [-48.1, -15.1]],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("geometry", response.data)

    def test_user_without_membership_cannot_list_properties(self):
        User = get_user_model()
        outsider = User.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="test-password-123",
        )
        client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        client.force_authenticate(outsider)

        response = client.get("/api/v1/properties/")

        self.assertEqual(response.status_code, 403)

    def test_viewer_can_read_but_cannot_change_property(self):
        create_response = self.client.post(
            "/api/v1/properties/",
            {"name": "Somente leitura", "geometry": self.polygon_geojson()},
            format="json",
        )
        property_id = create_response.data["id"]
        self.membership.role = Membership.Role.VIEWER
        self.membership.save(update_fields=("role", "updated_at"))

        detail = self.client.get(f"/api/v1/properties/{property_id}/")
        patch = self.client.patch(
            f"/api/v1/properties/{property_id}/",
            {"name": "Alteração proibida"},
            format="json",
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(patch.status_code, 403)

    def test_self_intersection_is_repaired_when_polygonal_result_is_safe(self):
        response = self.client.post(
            "/api/v1/properties/",
            {
                "name": "Polígono corrigido",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-48.01, -15.01],
                            [-48.00, -15.00],
                            [-48.01, -15.00],
                            [-48.00, -15.01],
                            [-48.01, -15.01],
                        ]
                    ],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["geometry"]["type"], "MultiPolygon")

    def test_tenant_cannot_access_property_from_another_schema(self):
        other = Tenant(schema_name="other_properties", name="Outro tenant")
        with schema_context("public"):
            other.save()
            Domain.objects.create(
                domain="other.test.localhost", tenant=other, is_primary=True
            )
        polygon = Polygon(
            (
                (-48.2, -15.2),
                (-48.2, -15.1),
                (-48.1, -15.1),
                (-48.1, -15.2),
                (-48.2, -15.2),
            ),
            srid=4326,
        )
        with tenant_context(other):
            foreign_property = Property.objects.create(
                name="Propriedade estrangeira",
                geometry=MultiPolygon(polygon, srid=4326),
                created_by=self.user,
            )

        response = self.client.get(f"/api/v1/properties/{foreign_property.id}/")

        self.assertEqual(response.status_code, 404)

    def test_import_shapefile_creates_property(self):
        upload = self._valid_shapefile_upload()

        response = self.client.post(
            "/api/v1/properties/import/",
            {"file": upload, "name": "CAR importado", "country": "BR"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["geometry"]["type"], "MultiPolygon")
        self.assertEqual(Property.objects.count(), 1)

    def test_zip_slip_is_rejected(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("../escape.shp", b"not-a-shapefile")
            archive.writestr("escape.shx", b"")
            archive.writestr("escape.dbf", b"")
            archive.writestr("escape.prj", b"")
        content.seek(0)
        upload = SimpleUploadedFile(
            "unsafe.zip", content.read(), content_type="application/zip"
        )

        response = self.client.post(
            "/api/v1/properties/import/",
            {"file": upload, "name": "ZIP inseguro"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data)
        self.assertEqual(Property.objects.count(), 0)

    def test_login_me_logout_and_blacklist(self):
        public_client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        login = public_client.post(
            "/api/v1/auth/login/",
            {"username": "agronomo", "password": "test-password-123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.assertEqual(login.data["tenant"]["role"], Membership.Role.AGRONOMIST)

        access = login.data["access"]
        refresh = login.data["refresh"]
        public_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        me = public_client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["email"], self.user.email)

        logout = public_client.post(
            "/api/v1/auth/logout/", {"refresh": refresh}, format="json"
        )
        self.assertEqual(logout.status_code, 204)
        refresh_response = public_client.post(
            "/api/v1/auth/refresh/", {"refresh": refresh}, format="json"
        )
        self.assertEqual(refresh_response.status_code, 401)

    @staticmethod
    def _valid_shapefile_upload() -> SimpleUploadedFile:
        polygon = ShapelyPolygon(
            [
                (-48.01, -15.01),
                (-48.01, -15.00),
                (-48.00, -15.00),
                (-48.00, -15.01),
                (-48.01, -15.01),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shapefile = root / "car.shp"
            frame = gpd.GeoDataFrame({"geometry": [polygon]}, crs="EPSG:4326")
            frame.to_file(shapefile, driver="ESRI Shapefile", engine="pyogrio")

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for component in root.glob("car.*"):
                    archive.write(component, arcname=component.name)
            buffer.seek(0)
            return SimpleUploadedFile(
                "car.zip",
                buffer.read(),
                content_type="application/zip",
            )
