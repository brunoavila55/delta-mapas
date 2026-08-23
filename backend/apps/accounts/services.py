from __future__ import annotations

from .models import Membership


def get_active_tenant_membership(*, user, tenant) -> Membership | None:
    """Return the active membership shared by API and browser authorization."""
    if (
        not user
        or not user.is_authenticated
        or tenant is None
        or tenant.schema_name == "public"
    ):
        return None
    return Membership.objects.filter(
        user=user,
        tenant=tenant,
        is_active=True,
    ).first()
