from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Membership
from apps.properties.models import Property


@override_settings(
    SECRET_KEY="test-secret-key-with-at-least-thirty-two-bytes",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class WebInterfaceTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Fazendas Delta"
        return tenant

    @staticmethod
    def get_test_schema_name():
        return "test_web"

    @staticmethod
    def get_test_tenant_domain():
        return "web.test.localhost"

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="operador",
            email="operador@example.com",
            password="senha-segura-123",
            first_name="Lia",
        )
        self.membership = Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=Membership.Role.AGRONOMIST,
        )
        self.client = Client(HTTP_HOST=self.get_test_tenant_domain())

    def login(self):
        response = self.client.post(
            "/login/",
            {"username": "operador", "password": "senha-segura-123"},
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/?next="))

    def test_health_is_available_without_an_api_namespace(self):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(self.client.get("/api/v1/health/").status_code, 404)
        self.assertEqual(self.client.get("/api/schema/").status_code, 404)

    def test_login_opens_server_rendered_dashboard(self):
        self.login()

        response = self.client.get("/")

        self.assertContains(response, "Bom trabalho, Lia")
        self.assertContains(response, "Fazendas Delta")
        self.assertContains(response, "Novo mapa NDVI")

    def test_property_can_be_created_from_geojson(self):
        self.login()
        response = self.client.post(
            "/properties/new/",
            {
                "name": "Talhão Norte",
                "city": "Cristalina",
                "state": "GO",
                "country": "BR",
                "description": "Área irrigada",
                "geometry": (
                    '{"type":"Polygon","coordinates":[[['
                    '-48.01,-15.01],[-48.01,-15.00],[-48.00,-15.00],'
                    '[-48.00,-15.01],[-48.01,-15.01]]]}'
                ),
            },
        )

        self.assertRedirects(response, "/properties/", fetch_redirect_response=False)
        self.assertTrue(Property.objects.filter(name="Talhão Norte").exists())

    def test_property_form_reports_domain_geojson_validation(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/properties/new/",
            {
                "name": "Geometria inválida",
                "country": "BR",
                "geometry": "não é geojson",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A geometria deve ser enviada como GeoJSON.")
        self.assertFalse(Property.objects.filter(name="Geometria inválida").exists())

    def test_htmx_property_search_returns_only_partial(self):
        self.login()
        response = self.client.get(
            "/properties/?search=inexistente", HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="property-list"')
        self.assertNotContains(response, "<!doctype html>")

    def test_main_pages_render_without_a_frontend_bundle(self):
        self.login()

        for path in ("/properties/", "/jobs/", "/jobs/new/", "/maps/", "/billing/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/web/css/app.css")
                self.assertNotContains(response, "/src/main.tsx")

    def test_viewer_cannot_open_mutating_pages(self):
        self.membership.role = Membership.Role.VIEWER
        self.membership.save(update_fields=("role", "updated_at"))
        self.login()

        response = self.client.get("/properties/new/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Ação restrita", status_code=403)
