from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Membership, User


@admin.register(User)
class DeltaUserAdmin(UserAdmin):
    pass


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "tenant__name")
