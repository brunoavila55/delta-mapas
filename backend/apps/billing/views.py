from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsActiveTenantMember

from .models import CreditAccount, CreditTransaction, ProcessingPrice
from .serializers import (
    CreditAccountSerializer,
    CreditTransactionSerializer,
    ProcessingPriceSerializer,
)


class CreditAccountView(APIView):
    permission_classes = (IsActiveTenantMember,)

    @extend_schema(responses=CreditAccountSerializer)
    def get(self, request):
        account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
        return Response(CreditAccountSerializer(account).data)


class CreditTransactionListView(generics.ListAPIView):
    permission_classes = (IsActiveTenantMember,)
    serializer_class = CreditTransactionSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ("created_at", "amount", "transaction_type")
    ordering = ("-created_at",)

    def get_queryset(self):
        queryset = CreditTransaction.objects.select_related("map_job").all()
        transaction_type = self.request.query_params.get("type")
        if transaction_type in CreditTransaction.Type.values:
            queryset = queryset.filter(transaction_type=transaction_type)
        return queryset


class ProcessingPriceListView(generics.ListAPIView):
    permission_classes = (IsActiveTenantMember,)
    serializer_class = ProcessingPriceSerializer
    pagination_class = None

    def get_queryset(self):
        return ProcessingPrice.objects.filter(is_active=True)
