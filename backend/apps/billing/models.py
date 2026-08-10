import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class CreditAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    singleton_key = models.BooleanField(default=True, unique=True, editable=False)
    available_balance = models.PositiveIntegerField(default=0, editable=False)
    reserved_balance = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return (
            f"{self.available_balance} disponíveis / {self.reserved_balance} reservados"
        )


class CreditTransaction(models.Model):
    class Type(models.TextChoices):
        PURCHASE = "PURCHASE", "Compra"
        RESERVE = "RESERVE", "Reserva"
        CAPTURE = "CAPTURE", "Captura"
        RELEASE = "RELEASE", "Liberação"
        REFUND = "REFUND", "Reembolso"
        BONUS = "BONUS", "Bônus"
        ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT", "Ajuste administrativo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        CreditAccount, on_delete=models.PROTECT, related_name="transactions"
    )
    transaction_type = models.CharField(max_length=24, choices=Type.choices)
    amount = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    idempotency_key = models.CharField(max_length=160, unique=True)
    map_job = models.ForeignKey(
        "maps.MapJob",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credit_transactions",
    )
    available_balance_after = models.PositiveIntegerField()
    reserved_balance_after = models.PositiveIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credit_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("transaction_type", "created_at")),
            models.Index(fields=("map_job", "transaction_type")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("map_job", "transaction_type"),
                condition=models.Q(map_job__isnull=False),
                name="billing_unique_job_transaction_type",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="billing_transaction_amount_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Credit ledger transactions are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Credit ledger transactions cannot be deleted.")

    def __str__(self) -> str:
        return f"{self.transaction_type}: {self.amount}"


class ProcessingPrice(models.Model):
    index_type = models.CharField(max_length=20, unique=True)
    credit_cost = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("index_type",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(credit_cost__gt=0),
                name="billing_processing_price_positive",
            )
        ]

    def __str__(self) -> str:
        return f"{self.index_type}: {self.credit_cost} crédito(s)"
