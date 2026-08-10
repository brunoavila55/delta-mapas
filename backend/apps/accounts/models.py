import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)

    def __str__(self) -> str:
        return self.email or self.username


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Proprietário"
        ADMIN = "ADMIN", "Administrador"
        AGRONOMIST = "AGRONOMIST", "Agrônomo"
        MEMBER = "MEMBER", "Membro"
        VIEWER = "VIEWER", "Visualizador"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "tenant"), name="accounts_unique_user_tenant"
            )
        ]
        indexes = [models.Index(fields=("tenant", "is_active"))]

    def __str__(self) -> str:
        return f"{self.user} @ {self.tenant} ({self.role})"
