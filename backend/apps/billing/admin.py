from django.contrib import admin

from .models import CreditAccount, CreditTransaction, ProcessingPrice


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "available_balance", "reserved_balance", "updated_at")
    readonly_fields = (
        "id",
        "singleton_key",
        "available_balance",
        "reserved_balance",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_type", "amount", "created_at", "idempotency_key")
    list_filter = ("transaction_type",)
    search_fields = ("idempotency_key", "map_job__id")
    readonly_fields = (
        "id",
        "account",
        "transaction_type",
        "amount",
        "idempotency_key",
        "map_job",
        "available_balance_after",
        "reserved_balance_after",
        "metadata",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProcessingPrice)
class ProcessingPriceAdmin(admin.ModelAdmin):
    list_display = ("index_type", "credit_cost", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("index_type",)
