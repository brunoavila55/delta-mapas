from __future__ import annotations

import hashlib
import ipaddress

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured


class LoginRateThrottle:
    cache_prefix = "login_rate"
    scope = ""
    rate_setting = ""

    def get_rate(self) -> str:
        return str(getattr(settings, self.rate_setting))

    def parse_rate(self, rate: str) -> tuple[int, int]:
        try:
            limit_text, period_text = rate.split("/", maxsplit=1)
            limit = int(limit_text)
            duration = {
                "s": 1,
                "sec": 1,
                "second": 1,
                "m": 60,
                "min": 60,
                "minute": 60,
                "h": 60 * 60,
                "hour": 60 * 60,
                "d": 24 * 60 * 60,
                "day": 24 * 60 * 60,
            }[period_text.strip().casefold()]
        except (KeyError, TypeError, ValueError) as exc:
            raise ImproperlyConfigured(
                f"{self.rate_setting} deve usar o formato quantidade/período."
            ) from exc
        if limit <= 0:
            raise ImproperlyConfigured(f"{self.rate_setting} deve ser positivo.")
        return limit, duration

    def get_cache_key(self, request, view=None):
        raise NotImplementedError

    def allow_request(self, request, view=None) -> bool:
        limit, duration = self.parse_rate(self.get_rate())
        key = self.get_cache_key(request, view)
        if key is None:
            return True
        if cache.add(key, 1, timeout=duration):
            return True
        try:
            attempts = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=duration)
            attempts = 1
        return attempts <= limit

    def format_cache_key(self, ident: str) -> str:
        return f"{self.cache_prefix}:{self.scope}:{ident}"


class LoginIPThrottle(LoginRateThrottle):
    scope = "login_ip"
    rate_setting = "LOGIN_IP_THROTTLE_RATE"

    def get_cache_key(self, request, view=None):
        ident = request.META.get("REMOTE_ADDR", "")
        if settings.DJANGO_TRUST_PROXY_HEADERS:
            forwarded = request.META.get("HTTP_X_DELTA_CLIENT_IP", "").strip()
            try:
                ident = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        return self.format_cache_key(ident)


class LoginAccountThrottle(LoginRateThrottle):
    scope = "login_account"
    rate_setting = "LOGIN_ACCOUNT_THROTTLE_RATE"

    def get_cache_key(self, request, view=None):
        username = str(request.POST.get("username", "")).strip().casefold()
        if not username:
            return None
        tenant = getattr(request, "tenant", None)
        tenant_key = str(
            getattr(tenant, "id", getattr(tenant, "schema_name", "public"))
        )
        digest = hashlib.sha256(f"{tenant_key}\0{username}".encode()).hexdigest()
        return self.format_cache_key(digest)


LOGIN_THROTTLE_CLASSES = (LoginIPThrottle, LoginAccountThrottle)


def login_rate_limit_exceeded(request) -> bool:
    """Apply the configured IP and account limits to a browser login."""
    for throttle_class in LOGIN_THROTTLE_CLASSES:
        if not throttle_class().allow_request(request):
            return True
    return False
