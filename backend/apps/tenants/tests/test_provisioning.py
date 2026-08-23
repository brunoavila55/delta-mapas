from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.tenants.management.commands.provision_tenant import configure_tenant_owner


class ProvisionTenantSecurityTests(SimpleTestCase):
    def test_tenant_owner_never_receives_platform_admin_privileges(self):
        user = SimpleNamespace(is_staff=True, is_superuser=True)

        configure_tenant_owner(user)

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
