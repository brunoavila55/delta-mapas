from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Membership, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name")
        read_only_fields = fields


class TenantContextSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    schema_name = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(choices=Membership.Role.choices, read_only=True)


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = UserSerializer(read_only=True)
    tenant = TenantContextSerializer(read_only=True)


class MeResponseSerializer(serializers.Serializer):
    user = UserSerializer(read_only=True)
    tenant = TenantContextSerializer(read_only=True)


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        tenant = getattr(self.context["request"], "tenant", None)
        membership = Membership.objects.filter(
            user=self.user,
            tenant=tenant,
            is_active=True,
        ).first()
        if membership is None or tenant.schema_name == "public":
            raise AuthenticationFailed("Usuário sem acesso ativo a esta organização.")

        data["user"] = UserSerializer(self.user).data
        data["tenant"] = {
            "id": str(tenant.id),
            "name": tenant.name,
            "schema_name": tenant.schema_name,
            "role": membership.role,
        }
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
