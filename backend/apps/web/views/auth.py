from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.services import get_active_tenant_membership
from apps.accounts.throttles import login_rate_limit_exceeded
from apps.billing.models import CreditAccount
from apps.maps.models import GeneratedMap, MapJob
from apps.properties.models import Property

from ..access import tenant_member_required
from ..forms import LoginForm


@require_http_methods(["GET", "POST"])
def login_view(request):
    tenant = getattr(request, "tenant", None)
    if get_active_tenant_membership(user=request.user, tenant=tenant):
        return redirect("web:dashboard")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        if login_rate_limit_exceeded(request):
            form.add_error(
                None,
                "Muitas tentativas. Aguarde um minuto e tente novamente.",
            )
        else:
            user = authenticate(
                request,
                username=username,
                password=form.cleaned_data["password"],
            )
            membership = get_active_tenant_membership(user=user, tenant=tenant)
            if user is None or membership is None:
                form.add_error(None, "Credenciais inválidas para esta organização.")
            else:
                login(request, user)
                target = request.POST.get("next") or reverse("web:dashboard")
                if not url_has_allowed_host_and_scheme(
                    target,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    target = reverse("web:dashboard")
                return redirect(target)

    return render(
        request,
        "web/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("web:login")


@tenant_member_required
@require_GET
def dashboard(request):
    account, _ = CreditAccount.objects.get_or_create(singleton_key=True)
    properties_qs = Property.objects.all()
    jobs_qs = MapJob.objects.select_related("property")
    active_statuses = set(MapJob.Status.values) - MapJob.Status.terminal_values()
    context = {
        "account": account,
        "property_count": properties_qs.count(),
        "total_area": properties_qs.aggregate(total=Sum("area_hectares"))["total"]
        or 0,
        "active_job_count": jobs_qs.filter(status__in=active_statuses).count(),
        "map_count": GeneratedMap.objects.count(),
        "recent_jobs": jobs_qs[:6],
        "recent_maps": GeneratedMap.objects.select_related("property")[:3],
    }
    return render(request, "web/dashboard.html", context)
