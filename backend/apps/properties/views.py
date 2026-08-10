from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import IsActiveTenantMember

from .exceptions import InvalidShapefile
from .importers import import_shapefile
from .models import Property
from .serializers import PropertySerializer, ShapefileImportSerializer


class PropertyViewSet(viewsets.ModelViewSet):
    serializer_class = PropertySerializer
    permission_classes = (IsActiveTenantMember,)
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = ("name", "city", "state")
    ordering_fields = ("name", "area_hectares", "created_at", "updated_at")
    ordering = ("name",)

    def get_queryset(self):
        return Property.objects.select_related("created_by").all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @extend_schema(
        request=ShapefileImportSerializer,
        responses={
            201: PropertySerializer,
            400: OpenApiResponse(description="ZIP ou shapefile inválido."),
        },
    )
    @action(
        detail=False,
        methods=("post",),
        url_path="import",
        parser_classes=(MultiPartParser, FormParser),
    )
    def import_shapefile(self, request):
        serializer = ShapefileImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            geometry = import_shapefile(data.pop("file"))
        except InvalidShapefile as exc:
            raise serializers.ValidationError({"file": exc.messages}) from exc

        with transaction.atomic():
            property_instance = Property.objects.create(
                geometry=geometry,
                created_by=request.user,
                **data,
            )
        response = PropertySerializer(property_instance, context={"request": request})
        return Response(response.data, status=status.HTTP_201_CREATED)
