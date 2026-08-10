from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Membership


class IsActiveTenantMember(BasePermission):
    message = "Você não possui acesso ativo a esta organização."
    writable_roles = {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.AGRONOMIST,
        Membership.Role.MEMBER,
    }

    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant:
            return False
        if tenant.schema_name == "public":
            return False

        membership = Membership.objects.filter(
            user=user,
            tenant=tenant,
            is_active=True,
        ).first()
        if membership is None:
            return False

        request.membership = membership
        if request.method in SAFE_METHODS:
            return True
        return membership.role in self.writable_roles
