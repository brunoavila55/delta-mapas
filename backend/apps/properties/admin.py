from django.contrib import admin

from .models import Property


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "area_hectares", "created_at")
    search_fields = ("name", "city", "state")
