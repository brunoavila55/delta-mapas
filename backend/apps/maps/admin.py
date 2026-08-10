from django.contrib import admin

from .models import GeneratedMap, MapJob


@admin.register(MapJob)
class MapJobAdmin(admin.ModelAdmin):
    list_display = ("id", "index_type", "status", "progress", "created_at")
    list_filter = ("status", "index_type")
    search_fields = ("id", "stac_item_id", "celery_task_id")


@admin.register(GeneratedMap)
class GeneratedMapAdmin(admin.ModelAdmin):
    list_display = ("id", "index_type", "scene_date", "created_at")
    list_filter = ("index_type",)
    search_fields = ("id", "stac_item_id")
