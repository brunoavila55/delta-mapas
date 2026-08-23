from django.core.paginator import Paginator

PAGE_SIZE = 12


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def safe_ordering(request, allowed: set[str], default: str) -> str:
    value = request.GET.get("ordering", default)
    return value if value in allowed else default


def paginate(request, queryset, page_size: int = PAGE_SIZE):
    return Paginator(queryset, page_size).get_page(request.GET.get("page"))
