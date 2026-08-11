from __future__ import annotations

import json

from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .exceptions import InvalidGeometry
from .models import Property
from .services import normalize_multipolygon, validate_area_limit


@extend_schema_field(
    {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["Polygon", "MultiPolygon"]},
            "coordinates": {"type": "array", "items": {}},
        },
    }
)
class GeometryField(serializers.Field):
    def to_representation(self, value):
        return json.loads(value.geojson)

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get("type") == "Feature":
            data = data.get("geometry")
        if not isinstance(data, (dict, str)):
            self.fail("invalid")
        try:
            raw = data if isinstance(data, str) else json.dumps(data)
            geometry = GEOSGeometry(raw)
            normalized = normalize_multipolygon(geometry)
            validate_area_limit(normalized)
            return normalized
        except InvalidGeometry as exc:
            raise serializers.ValidationError(exc.messages) from exc
        except (GEOSException, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise serializers.ValidationError(str(exc)) from exc


class PropertySerializer(serializers.ModelSerializer):
    geometry = GeometryField()

    class Meta:
        model = Property
        fields = (
            "id",
            "name",
            "description",
            "geometry",
            "area_hectares",
            "city",
            "state",
            "country",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "area_hectares",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate_country(self, value: str) -> str:
        if len(value.strip()) != 2:
            raise serializers.ValidationError(
                "Use o código ISO de duas letras do país."
            )
        return value.strip().upper()


class ShapefileImportSerializer(serializers.Serializer):
    file = serializers.FileField(write_only=True)
    name = serializers.CharField(max_length=180)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    city = serializers.CharField(
        required=False, allow_blank=True, max_length=120, default=""
    )
    state = serializers.CharField(
        required=False, allow_blank=True, max_length=120, default=""
    )
    country = serializers.CharField(required=False, max_length=2, default="BR")

    def validate_file(self, value):
        if not value.name.lower().endswith(".zip"):
            raise serializers.ValidationError("Envie um arquivo com extensão .zip.")
        return value

    def validate_country(self, value: str) -> str:
        if len(value.strip()) != 2:
            raise serializers.ValidationError(
                "Use o código ISO de duas letras do país."
            )
        return value.strip().upper()
