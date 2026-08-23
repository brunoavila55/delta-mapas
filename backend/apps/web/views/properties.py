from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.properties.models import Property

from ..access import tenant_editor_required, tenant_member_required
from ..forms import PropertyForm
from ._helpers import is_htmx, paginate, safe_ordering


def _property_queryset(request):
    queryset = Property.objects.select_related("created_by")
    search = request.GET.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(city__icontains=search)
            | Q(state__icontains=search)
        )
    ordering = safe_ordering(
        request,
        {"name", "-name", "-created_at", "-area_hectares"},
        "name",
    )
    return queryset.order_by(ordering), search, ordering


@tenant_member_required
@require_GET
def properties(request):
    queryset, search, ordering = _property_queryset(request)
    context = {
        "page_obj": paginate(request, queryset),
        "search": search,
        "ordering": ordering,
    }
    template = (
        "web/partials/property_list.html" if is_htmx(request) else "web/properties.html"
    )
    return render(request, template, context)


@tenant_editor_required
@require_http_methods(["GET", "POST"])
def property_form(request, pk=None):
    instance = get_object_or_404(Property, pk=pk) if pk else None
    form = PropertyForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            if instance is None:
                instance = Property(created_by=request.user)
            instance.name = data["name"]
            instance.city = data["city"]
            instance.state = data["state"]
            instance.country = data["country"]
            instance.description = data["description"]
            instance.geometry = data["normalized_geometry"]
            instance.save()
        messages.success(request, f"{instance.name} foi salva com sucesso.")
        return redirect("web:properties")
    return render(
        request,
        "web/property_form.html",
        {"form": form, "property": instance},
    )


@tenant_editor_required
@require_POST
def property_delete(request, pk):
    property_instance = get_object_or_404(Property, pk=pk)
    name = property_instance.name
    try:
        property_instance.delete()
    except ProtectedError:
        messages.error(
            request,
            "Esta propriedade possui histórico protegido e não pode ser excluída.",
        )
        return redirect("web:properties")
    if is_htmx(request):
        return HttpResponse(status=200)
    messages.success(request, f"{name} foi removida.")
    return redirect("web:properties")
