from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.models import Membership
from apps.accounts.services import get_active_tenant_membership


def _login_redirect(request):
    target = f"{reverse('web:login')}?{urlencode({'next': request.get_full_path()})}"
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
        return response
    return redirect(target)


def tenant_member_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login_redirect(request)
        membership = get_active_tenant_membership(
            user=request.user,
            tenant=getattr(request, "tenant", None),
        )
        if membership is None:
            logout(request)
            return _login_redirect(request)
        request.membership = membership
        return view(request, *args, **kwargs)

    return wrapped


def tenant_editor_required(view):
    @tenant_member_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.membership.role == Membership.Role.VIEWER:
            return render(request, "web/403.html", status=403)
        return view(request, *args, **kwargs)

    return wrapped
