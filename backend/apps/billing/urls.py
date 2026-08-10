from django.urls import path

from .views import CreditAccountView, CreditTransactionListView, ProcessingPriceListView

urlpatterns = [
    path("account/", CreditAccountView.as_view(), name="credit-account"),
    path(
        "transactions/", CreditTransactionListView.as_view(), name="credit-transactions"
    ),
    path("prices/", ProcessingPriceListView.as_view(), name="processing-prices"),
]
