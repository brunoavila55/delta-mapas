from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.maps.models import GeneratedMap

from ..access import tenant_member_required
from ._helpers import is_htmx, paginate, safe_ordering


@tenant_member_required
@require_GET
def maps(request):
    queryset = GeneratedMap.objects.select_related("property", "job")
    search = request.GET.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(property__name__icontains=search) | Q(stac_item_id__icontains=search)
        )
    ordering = safe_ordering(
        request,
        {"-created_at", "created_at", "-scene_date", "cloud_cover"},
        "-created_at",
    )
    context = {
        "page_obj": paginate(request, queryset.order_by(ordering), 9),
        "search": search,
        "ordering": ordering,
    }
    template = "web/partials/map_list.html" if is_htmx(request) else "web/maps.html"
    return render(request, template, context)


@tenant_member_required
@require_GET
def map_file(request, pk, file_format):
    generated_map = get_object_or_404(GeneratedMap, pk=pk)
    if file_format not in {"png", "pdf"}:
        raise Http404
    field = generated_map.png_file if file_format == "png" else generated_map.pdf_file
    try:
        stream = field.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("Arquivo não encontrado.") from exc
    download = request.GET.get("download") == "1"
    return FileResponse(
        stream,
        as_attachment=download,
        filename=f"delta-mapas-{generated_map.id}.{file_format}",
        content_type="image/png" if file_format == "png" else "application/pdf",
    )
