from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .permissions import IsActiveTenantMember
from .serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
    MeResponseSerializer,
    UserSerializer,
)


class LoginView(TokenObtainPairView):
    permission_classes = (AllowAny,)
    serializer_class = LoginSerializer

    @extend_schema(responses=LoginResponseSerializer)
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)


class MeView(APIView):
    permission_classes = (IsActiveTenantMember,)

    @extend_schema(responses=MeResponseSerializer)
    def get(self, request):
        tenant = request.tenant
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "tenant": {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "schema_name": tenant.schema_name,
                    "role": request.membership.role,
                },
            }
        )


class LogoutView(APIView):
    permission_classes = (IsActiveTenantMember,)

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": "Token inválido."}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)
