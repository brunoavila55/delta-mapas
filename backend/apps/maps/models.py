import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection
from django.utils import timezone


class IndexType(models.TextChoices):
    NDVI = "NDVI", "NDVI"


class MapJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        SEARCHING_SCENE = "SEARCHING_SCENE", "Buscando cena"
        DOWNLOADING = "DOWNLOADING", "Baixando"
        PREPROCESSING = "PREPROCESSING", "Pré-processando"
        PROCESSING = "PROCESSING", "Processando"
        RENDERING = "RENDERING", "Renderizando"
        UPLOADING = "UPLOADING", "Enviando"
        COMPLETED = "COMPLETED", "Concluído"
        FAILED = "FAILED", "Falhou"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING
    )
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    current_step = models.CharField(max_length=160, blank=True)
    index_type = models.CharField(
        max_length=20, choices=IndexType.choices, default=IndexType.NDVI
    )
    geometry_snapshot = models.MultiPolygonField(srid=4326)
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="map_jobs",
    )
    requested_scene_date = models.DateField(null=True, blank=True)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    max_cloud_cover = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    stac_item_id = models.CharField(max_length=255, blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    credit_cost = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    request_idempotency_key = models.CharField(
        max_length=160, unique=True, null=True, blank=True
    )
    request_fingerprint = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="map_jobs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("created_by", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.index_type} {self.id} ({self.status})"


def generated_map_upload_to(instance: "GeneratedMap", filename: str) -> str:
    tenant = getattr(connection, "tenant", None)
    tenant_id = getattr(tenant, "id", "unknown")
    created = instance.created_at or timezone.now()
    suffix = Path(filename).suffix.lower()
    safe_name = "map.pdf" if suffix == ".pdf" else "map.png"
    return f"tenants/{tenant_id}/maps/{created:%Y/%m}/{instance.id}/{safe_name}"


class GeneratedMap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        MapJob, on_delete=models.PROTECT, related_name="generated_map"
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_maps",
    )
    index_type = models.CharField(max_length=20, choices=IndexType.choices)
    geometry_snapshot = models.MultiPolygonField(srid=4326)
    scene_date = models.DateTimeField()
    stac_item_id = models.CharField(max_length=255)
    cloud_cover = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    png_file = models.FileField(upload_to=generated_map_upload_to)
    pdf_file = models.FileField(upload_to=generated_map_upload_to)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_maps",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("index_type", "created_at"))]

    def __str__(self) -> str:
        return f"{self.index_type} {self.scene_date:%Y-%m-%d}"
