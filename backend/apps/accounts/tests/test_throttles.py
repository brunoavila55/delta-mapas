from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.throttles import (
    LoginAccountThrottle,
    LoginIPThrottle,
    login_rate_limit_exceeded,
)


@override_settings(
    LOGIN_IP_THROTTLE_RATE="2/min",
    LOGIN_ACCOUNT_THROTTLE_RATE="2/min",
)
class LoginThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def request(self, username="owner", ip="203.0.113.10"):
        request = self.factory.post(
            "/login/",
            {"username": username, "password": "wrong"},
            REMOTE_ADDR=ip,
        )
        request.tenant = SimpleNamespace(id="tenant-a")
        return request

    def test_login_limits_ip_and_account_independently(self):
        for throttle_class in (LoginIPThrottle, LoginAccountThrottle):
            cache.clear()
            throttle = throttle_class()

            self.assertTrue(throttle.allow_request(self.request()))
            self.assertTrue(throttle.allow_request(self.request()))
            self.assertFalse(throttle.allow_request(self.request()))

    def test_account_key_does_not_store_the_username(self):
        key = LoginAccountThrottle().get_cache_key(self.request("Secret.Owner"))

        self.assertNotIn("secret.owner", key.lower())
        self.assertNotEqual(
            key,
            LoginAccountThrottle().get_cache_key(self.request("other")),
        )

    def test_combined_limiter_stops_after_configured_attempts(self):
        self.assertFalse(login_rate_limit_exceeded(self.request()))
        self.assertFalse(login_rate_limit_exceeded(self.request()))
        self.assertTrue(login_rate_limit_exceeded(self.request()))

    @override_settings(DJANGO_TRUST_PROXY_HEADERS=True)
    def test_ip_key_uses_only_the_proxy_overwritten_client_header(self):
        request = self.request(ip="10.0.0.5")
        request.META["HTTP_X_FORWARDED_FOR"] = "198.51.100.1"
        request.META["HTTP_X_DELTA_CLIENT_IP"] = "203.0.113.7"

        key = LoginIPThrottle().get_cache_key(request)

        self.assertIn("203.0.113.7", key)
        self.assertNotIn("198.51.100.1", key)

    def test_rate_can_be_changed_without_code_changes(self):
        throttle = LoginAccountThrottle()
        with patch.object(throttle, "get_rate", return_value="1/hour"):
            self.assertTrue(throttle.allow_request(self.request()))
            self.assertFalse(throttle.allow_request(self.request()))
