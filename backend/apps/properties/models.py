import uuid

from django.conf import settings
from django.contrib.gis.db import models

from .services import calculate_area_hectares, normalize_multipolygon


class Property(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    geometry = models.MultiPolygonField(srid=4326, spatial_index=True)
    area_hectares = models.DecimalField(max_digits=14, decimal_places=4, editable=False)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=2, default="BR")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_properties",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "properties"
        indexes = [models.Index(fields=("created_at",))]

    def save(self, *args, **kwargs):
        self.geometry = normalize_multipolygon(self.geometry)
        self.area_hectares = calculate_area_hectares(self.geometry)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name
