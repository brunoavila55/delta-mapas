from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests
from django.conf import settings

from ..exceptions import (
    CopernicusAuthenticationError,
    CopernicusAuthenticationUnavailable,
    CopernicusConfigurationError,
)


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    expires_at: float


class OAuthTokenProvider:
    def __init__(
        self,
        *,
        session: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session or requests.Session()
        self._clock = clock
        self._cached_token: AccessToken | None = None
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._cached_token = None

    def get_access_token(self) -> str:
        with self._lock:
            now = self._clock()
            leeway = settings.COPERNICUS_TOKEN_REFRESH_LEEWAY_SECONDS
            if self._cached_token and self._cached_token.expires_at > now + leeway:
                return self._cached_token.value

            client_id = settings.COPERNICUS_CLIENT_ID
            client_secret = settings.COPERNICUS_CLIENT_SECRET
            if not client_id or not client_secret:
                raise CopernicusConfigurationError(
                    "Credenciais OAuth do Copernicus não foram configuradas."
                )

            try:
                response = self._session.post(
                    settings.COPERNICUS_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=settings.COPERNICUS_AUTH_TIMEOUT_SECONDS,
                    stream=True,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise CopernicusAuthenticationUnavailable(
                    "O serviço de autenticação do Copernicus está indisponível."
                ) from exc

            try:
                if response.status_code == 429 or response.status_code >= 500:
                    raise CopernicusAuthenticationUnavailable(
                        "O serviço de autenticação do Copernicus está indisponível."
                    )
                if response.status_code >= 300:
                    raise CopernicusAuthenticationError(
                        "As credenciais OAuth do Copernicus foram recusadas."
                    )

                maximum_bytes = settings.COPERNICUS_AUTH_MAX_RESPONSE_BYTES
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_bytes = int(content_length)
                    except ValueError as exc:
                        raise CopernicusAuthenticationError(
                            "A resposta de autenticação do Copernicus é inválida."
                        ) from exc
                    if declared_bytes < 0 or declared_bytes > maximum_bytes:
                        raise CopernicusAuthenticationError(
                            "A resposta de autenticação do Copernicus excede o limite."
                        )
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > maximum_bytes:
                        raise CopernicusAuthenticationError(
                            "A resposta de autenticação do Copernicus excede o limite."
                        )
                payload = json.loads(body.decode("utf-8"))
                token_value = payload["access_token"]
                expires_in = int(payload["expires_in"])
            except requests.RequestException as exc:
                raise CopernicusAuthenticationUnavailable(
                    "O serviço de autenticação do Copernicus está indisponível."
                ) from exc
            except (
                KeyError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise CopernicusAuthenticationError(
                    "A resposta de autenticação do Copernicus é inválida."
                ) from exc
            finally:
                response.close()

            if not isinstance(token_value, str) or not token_value or expires_in <= 0:
                raise CopernicusAuthenticationError(
                    "A resposta de autenticação do Copernicus é inválida."
                )

            self._cached_token = AccessToken(
                value=token_value,
                expires_at=now + expires_in,
            )
            return token_value
