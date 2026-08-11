import uuid

from django.conf import settings
from rest_framework import serializers

from apps.properties.models import Property
from apps.properties.serializers import GeometryField

from .models import GeneratedMap, IndexType, MapJob


class MapJobSerializer(serializers.ModelSerializer):
    geometry_snapshot = GeometryField(read_only=True)
    property_id = serializers.UUIDField(read_only=True, allow_null=True)
    property_name = serializers.CharField(
        source="property.name", read_only=True, allow_null=True
    )
    generated_map_id = serializers.SerializerMethodField()
    reprocessed_from_id = serializers.UUIDField(read_only=True, allow_null=True)

    def get_generated_map_id(self, obj) -> uuid.UUID | None:
        generated_map = getattr(obj, "generated_map", None)
        return generated_map.id if generated_map else None

    class Meta:
        model = MapJob
        fields = (
            "id",
            "status",
            "progress",
            "current_step",
            "index_type",
            "geometry_snapshot",
            "property_id",
            "property_name",
            "requested_scene_date",
            "date_from",
            "date_to",
            "max_cloud_cover",
            "stac_item_id",
            "error_code",
            "error_message",
            "credit_cost",
            "created_by",
            "created_at",
            "heartbeat_at",
            "started_at",
            "finished_at",
            "cancelled_at",
            "cancelled_by",
            "reprocessed_from_id",
            "generated_map_id",
        )
        read_only_fields = fields


class MapJobCreateSerializer(serializers.Serializer):
    index_type = serializers.ChoiceField(
        choices=IndexType.choices, default=IndexType.NDVI
    )
    property_id = serializers.UUIDField(required=False)
    geometry = GeometryField(required=False, write_only=True)
    requested_scene_date = serializers.DateField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    max_cloud_cover = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        default=20,
    )

    def validate(self, attrs):
        property_id = attrs.pop("property_id", None)
        geometry = attrs.pop("geometry", None)
        if bool(property_id) == bool(geometry):
            raise serializers.ValidationError(
                "Informe exatamente um entre property_id e geometry."
            )

        property_instance = None
        if property_id:
            try:
                property_instance = Property.objects.get(pk=property_id)
            except Property.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"property_id": "Propriedade não encontrada."}
                ) from exc
            geometry = property_instance.geometry.clone()

        requested_scene_date = attrs.get("requested_scene_date")
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if requested_scene_date and (date_from or date_to):
            raise serializers.ValidationError(
                "Use requested_scene_date ou o intervalo date_from/date_to."
            )
        if not requested_scene_date and not (date_from and date_to):
            raise serializers.ValidationError(
                "Informe requested_scene_date ou o intervalo completo date_from/date_to."
            )
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_to": "A data final deve ser posterior à inicial."}
            )
        maximum_days = settings.MAP_MAX_DATE_RANGE_DAYS
        if maximum_days > 0 and date_from and date_to:
            if (date_to - date_from).days > maximum_days:
                raise serializers.ValidationError(
                    {"date_to": f"O intervalo máximo é de {maximum_days} dias."}
                )

        attrs["property_instance"] = property_instance
        attrs["geometry_snapshot"] = geometry
        return attrs


class GeneratedMapSerializer(serializers.ModelSerializer):
    geometry_snapshot = GeometryField(read_only=True)
    property_id = serializers.UUIDField(read_only=True, allow_null=True)
    property_name = serializers.CharField(
        source="property.name", read_only=True, allow_null=True
    )
    png_download_url = serializers.SerializerMethodField()
    pdf_download_url = serializers.SerializerMethodField()

    def _download_url(self, obj, file_format: str) -> str:
        request = self.context.get("request")
        path = f"/api/v1/maps/{obj.id}/download/{file_format}/"
        return request.build_absolute_uri(path) if request else path

    def get_png_download_url(self, obj) -> str:
        return self._download_url(obj, "png")

    def get_pdf_download_url(self, obj) -> str:
        return self._download_url(obj, "pdf")

    class Meta:
        model = GeneratedMap
        fields = (
            "id",
            "job_id",
            "property_id",
            "property_name",
            "index_type",
            "geometry_snapshot",
            "scene_date",
            "stac_item_id",
            "cloud_cover",
            "metadata",
            "png_download_url",
            "pdf_download_url",
            "created_by",
            "created_at",
        )
        read_only_fields = fields
