import uuid
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.billing.exceptions import InsufficientCredits, ProcessingPriceNotConfigured
from apps.billing.models import CreditAccount, ProcessingPrice
from apps.maps.exceptions import (
    MapJobEnqueueError,
    MapJobIdempotencyConflict,
    MapJobTransitionConflict,
)
from apps.maps.models import MapJob
from apps.maps.services import create_map_job
from apps.maps.services.lifecycle import cancel_map_job, reprocess_map_job

from ..access import tenant_editor_required, tenant_member_required
from ..forms import MapJobForm
from ._helpers import is_htmx, paginate, safe_ordering


def _job_queryset(request):
    queryset = MapJob.objects.select_related("property", "generated_map")
    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()
    if search:
        queryset = queryset.filter(
            Q(property__name__icontains=search)
            | Q(stac_item_id__icontains=search)
            | Q(current_step__icontains=search)
        )
    if status in MapJob.Status.values:
        queryset = queryset.filter(status=status)
    ordering = safe_ordering(
        request,
        {"-created_at", "created_at", "-progress"},
        "-created_at",
    )
    return queryset.order_by(ordering), search, status, ordering


def _jobs_context(request):
    queryset, search, status, ordering = _job_queryset(request)
    page_obj = paginate(request, queryset)
    active = any(job.status not in MapJob.Status.terminal_values() for job in page_obj)
    return {
        "page_obj": page_obj,
        "search": search,
        "selected_status": status,
        "ordering": ordering,
        "status_choices": MapJob.Status.choices,
        "has_active_jobs": active,
    }


@tenant_member_required
@require_GET
def jobs(request):
    template = "web/partials/job_list.html" if is_htmx(request) else "web/jobs.html"
    return render(request, template, _jobs_context(request))


@tenant_editor_required
@require_http_methods(["GET", "POST"])
def job_create(request):
    form = MapJobForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        property_instance = data["property"]
        try:
            create_map_job(
                created_by=request.user,
                idempotency_key=f"web:{request.user.id}:{uuid.uuid4()}",
                index_type=data["index_type"],
                geometry_snapshot=property_instance.geometry.clone(),
                property_instance=property_instance,
                date_from=data["date_from"],
                date_to=data["date_to"],
                max_cloud_cover=data["max_cloud_cover"],
            )
        except (
            InsufficientCredits,
            ProcessingPriceNotConfigured,
            MapJobEnqueueError,
            MapJobIdempotencyConflict,
        ) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Processamento enviado para a fila.")
            return redirect("web:jobs")
    account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
    price = ProcessingPrice.objects.filter(index_type="NDVI", is_active=True).first()
    return render(
        request,
        "web/job_form.html",
        {
            "form": form,
            "account": account,
            "price": price,
            "suggested_date_from": timezone.localdate() - timedelta(days=30),
            "suggested_date_to": timezone.localdate(),
        },
    )


@tenant_editor_required
@require_POST
def job_cancel(request, pk):
    try:
        job, _ = cancel_map_job(job_id=pk, cancelled_by=request.user)
    except (MapJob.DoesNotExist, MapJobTransitionConflict) as exc:
        messages.error(request, str(exc) or "Processamento não encontrado.")
        return redirect("web:jobs")
    if is_htmx(request):
        return render(
            request,
            "web/partials/job_row.html",
            {"job": job, "action_message": "Processamento cancelado."},
        )
    messages.success(request, "Processamento cancelado.")
    return redirect("web:jobs")


@tenant_editor_required
@require_POST
def job_reprocess(request, pk):
    source = get_object_or_404(MapJob, pk=pk)
    try:
        reprocess_map_job(
            source_job=source,
            created_by=request.user,
            idempotency_key=f"web:reprocess:{source.id}:{uuid.uuid4()}",
        )
    except (
        MapJobTransitionConflict,
        InsufficientCredits,
        ProcessingPriceNotConfigured,
        MapJobEnqueueError,
        MapJobIdempotencyConflict,
    ) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Reprocessamento enviado para a fila.")
    response = HttpResponse(status=204) if is_htmx(request) else redirect("web:jobs")
    if is_htmx(request):
        response["HX-Redirect"] = reverse("web:jobs")
    return response
