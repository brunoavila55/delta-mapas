from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone
from redis import Redis

from .operations import ReconciliationBatchReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertDelivery:
    attempted: bool
    delivered: bool
    suppressed: bool = False
    error: str = ""

    @property
    def status(self) -> str:
        if self.suppressed:
            return "suppressed"
        if self.delivered:
            return "delivered"
        if self.attempted or self.error:
            return "failed"
        return "logging_only"


def _fingerprint(value: dict[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def build_reconciliation_alert(
    report: ReconciliationBatchReport,
) -> dict[str, Any] | None:
    if report.skipped_locked or not report.has_issues:
        return None

    totals = report.totals
    affected_tenants = [
        {
            "tenant_id": str(item.tenant_id),
            "schema_name": item.schema_name,
            "stalled_candidates": item.stalled_candidates,
            "expired_jobs": item.expired_jobs,
            "missing_files": item.missing_files,
            "orphan_objects": item.orphan_objects,
            "deleted_objects": item.deleted_objects,
            "errors": list(item.errors),
        }
        for item in report.tenants
        if item.has_issues
    ]
    severity = (
        "critical" if totals["failed_tenants"] or totals["missing_files"] else "warning"
    )
    incident = {
        "totals": totals,
        "affected_tenants": affected_tenants,
    }
    return {
        "event": "map_reconciliation_anomaly",
        "severity": severity,
        "occurred_at": report.finished_at.isoformat(),
        "summary": (
            f"Reconciliação encontrou anomalias em {len(affected_tenants)} tenant(s)."
        ),
        "incident": incident,
        "dedupe_key": _fingerprint(incident),
    }


def build_reconciliation_failure_alert(error_type: str) -> dict[str, Any]:
    incident = {"error_type": error_type}
    return {
        "event": "map_reconciliation_failed",
        "severity": "critical",
        "occurred_at": timezone.now().isoformat(),
        "summary": "A reconciliação agendada falhou antes de concluir.",
        "incident": incident,
        "dedupe_key": _fingerprint(incident),
    }


def _webhook_url_is_allowed(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme == "https" or (
        scheme == "http" and settings.OPERATIONS_ALERT_ALLOW_INSECURE_HTTP
    )


def deliver_operations_alert(
    payload: dict[str, Any],
    *,
    redis_client: Redis | None = None,
    http_post=None,
) -> AlertDelivery:
    url = settings.OPERATIONS_ALERT_WEBHOOK_URL
    if not url:
        return AlertDelivery(attempted=False, delivered=False)
    if not _webhook_url_is_allowed(url):
        return AlertDelivery(
            attempted=False,
            delivered=False,
            error="webhook_url_must_use_https",
        )

    dedupe_key = f"delta-mapas:operations-alert:{payload['dedupe_key']}"
    try:
        redis_client = redis_client or Redis.from_url(settings.CELERY_BROKER_URL)
        if redis_client.exists(dedupe_key):
            return AlertDelivery(
                attempted=False,
                delivered=False,
                suppressed=True,
            )
    except Exception:
        redis_client = None
        logger.warning("Operational alert deduplication is unavailable", exc_info=True)

    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "delta-mapas-operations/1.0",
        "X-Delta-Mapas-Event": str(payload["event"]),
    }
    if settings.OPERATIONS_ALERT_WEBHOOK_SECRET:
        signature = hmac.new(
            settings.OPERATIONS_ALERT_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers["X-Delta-Mapas-Signature"] = f"sha256={signature}"

    try:
        post = http_post or requests.post
        response = post(
            url,
            data=body,
            headers=headers,
            timeout=settings.OPERATIONS_ALERT_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise requests.HTTPError(
                f"Unexpected webhook status: {response.status_code}"
            )
        response.raise_for_status()
    except requests.RequestException as exc:
        return AlertDelivery(
            attempted=True,
            delivered=False,
            error=type(exc).__name__,
        )

    if redis_client is not None:
        try:
            redis_client.set(
                dedupe_key,
                "1",
                ex=settings.OPERATIONS_ALERT_COOLDOWN_SECONDS,
            )
        except Exception:
            logger.warning(
                "Operational alert cooldown could not be persisted", exc_info=True
            )

    return AlertDelivery(attempted=True, delivered=True)
