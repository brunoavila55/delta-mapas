from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.billing.models import CreditAccount, CreditTransaction, ProcessingPrice

from ..access import tenant_member_required
from ._helpers import is_htmx, paginate, safe_ordering


@tenant_member_required
@require_GET
def billing(request):
    account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
    queryset = CreditTransaction.objects.select_related("map_job")
    selected_type = request.GET.get("type", "")
    if selected_type in CreditTransaction.Type.values:
        queryset = queryset.filter(transaction_type=selected_type)
    ordering = safe_ordering(
        request,
        {"-created_at", "created_at", "-amount"},
        "-created_at",
    )
    context = {
        "account": account,
        "price": ProcessingPrice.objects.filter(
            index_type="NDVI",
            is_active=True,
        ).first(),
        "page_obj": paginate(request, queryset.order_by(ordering)),
        "type_choices": CreditTransaction.Type.choices,
        "selected_type": selected_type,
        "ordering": ordering,
    }
    template = (
        "web/partials/billing_ledger.html" if is_htmx(request) else "web/billing.html"
    )
    return render(request, template, context)
