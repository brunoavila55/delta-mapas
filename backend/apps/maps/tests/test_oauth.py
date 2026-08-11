from unittest.mock import Mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.maps.exceptions import (
    CopernicusAuthenticationError,
    CopernicusAuthenticationUnavailable,
    CopernicusConfigurationError,
)
from apps.maps.services.oauth import OAuthTokenProvider


@override_settings(
    COPERNICUS_CLIENT_ID="oauth-client",
    COPERNICUS_CLIENT_SECRET="oauth-secret",
    COPERNICUS_TOKEN_URL="https://identity.example.test/token",
    COPERNICUS_AUTH_TIMEOUT_SECONDS=12,
    COPERNICUS_TOKEN_REFRESH_LEEWAY_SECONDS=60,
)
class OAuthTokenProviderTests(SimpleTestCase):
    def response(self, *, status=200, payload=None):
        response = Mock()
        response.status_code = status
        response.json.return_value = payload or {
            "access_token": "short-lived-token",
            "expires_in": 600,
        }
        return response

    def test_requests_and_reuses_token_without_exposing_credentials(self):
        session = Mock()
        session.post.return_value = self.response()
        clock = Mock(return_value=1000.0)
        provider = OAuthTokenProvider(session=session, clock=clock)

        first = provider.get_access_token()
        second = provider.get_access_token()

        self.assertEqual(first, "short-lived-token")
        self.assertEqual(second, first)
        session.post.assert_called_once_with(
            "https://identity.example.test/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "oauth-client",
                "client_secret": "oauth-secret",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=12,
        )

    def test_refreshes_token_inside_expiry_leeway(self):
        session = Mock()
        session.post.side_effect = [
            self.response(payload={"access_token": "first", "expires_in": 120}),
            self.response(payload={"access_token": "second", "expires_in": 120}),
        ]
        current_time = [1000.0]
        provider = OAuthTokenProvider(
            session=session,
            clock=lambda: current_time[0],
        )

        self.assertEqual(provider.get_access_token(), "first")
        current_time[0] = 1061.0
        self.assertEqual(provider.get_access_token(), "second")
        self.assertEqual(session.post.call_count, 2)

    @override_settings(COPERNICUS_CLIENT_ID="", COPERNICUS_CLIENT_SECRET="")
    def test_rejects_missing_configuration_without_network_request(self):
        session = Mock()
        provider = OAuthTokenProvider(session=session)

        with self.assertRaises(CopernicusConfigurationError):
            provider.get_access_token()

        session.post.assert_not_called()

    def test_distinguishes_invalid_credentials_from_temporary_failures(self):
        rejected_session = Mock()
        rejected_session.post.return_value = self.response(status=401)
        with self.assertRaises(CopernicusAuthenticationError):
            OAuthTokenProvider(session=rejected_session).get_access_token()

        unavailable_session = Mock()
        unavailable_session.post.return_value = self.response(status=503)
        with self.assertRaises(CopernicusAuthenticationUnavailable):
            OAuthTokenProvider(session=unavailable_session).get_access_token()

        timeout_session = Mock()
        timeout_session.post.side_effect = requests.Timeout("timeout")
        with self.assertRaises(CopernicusAuthenticationUnavailable):
            OAuthTokenProvider(session=timeout_session).get_access_token()

    def test_rejects_invalid_success_payload(self):
        session = Mock()
        session.post.return_value = self.response(payload={"expires_in": 600})

        with self.assertRaises(CopernicusAuthenticationError):
            OAuthTokenProvider(session=session).get_access_token()
