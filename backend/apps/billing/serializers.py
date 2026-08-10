from rest_framework import serializers

from .models import CreditAccount, CreditTransaction, ProcessingPrice


class CreditAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditAccount
        fields = ("id", "available_balance", "reserved_balance", "updated_at")
        read_only_fields = fields


class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = (
            "id",
            "transaction_type",
            "amount",
            "map_job",
            "available_balance_after",
            "reserved_balance_after",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class ProcessingPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingPrice
        fields = ("index_type", "credit_cost")
        read_only_fields = fields
