from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from apps.maps.services.alerts import (
    AlertDelivery,
    build_reconciliation_alert,
    deliver_operations_alert,
)
from apps.maps.services.operations import (
    ReconciliationBatchReport,
    TenantReconciliationResult,
)
from apps.maps.tasks import reconcile_all_tenants


class FakeRedis:
    def __init__(self, *, duplicate=False):
        self.duplicate = duplicate
        self.saved = None

    def exists(self, key):
        return int(self.duplicate)

    def set(self, key, value, *, ex):
        self.saved = (key, value, ex)


def batch_report(*tenant_results):
    started_at = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    return ReconciliationBatchReport(
        started_at=started_at,
        finished_at=started_at,
        tenants=tuple(tenant_results),
    )


class OperationsAlertTests(SimpleTestCase):
    def test_healthy_reconciliation_does_not_create_alert(self):
        report = batch_report(
            TenantReconciliationResult(
                tenant_id=uuid4(),
                schema_name="healthy",
                expected_objects=4,
            )
        )

        self.assertIsNone(build_reconciliation_alert(report))

    def test_missing_file_creates_stable_critical_alert(self):
        tenant_id = uuid4()
        report = batch_report(
            TenantReconciliationResult(
                tenant_id=tenant_id,
                schema_name="principal",
                expected_objects=2,
                missing_files=1,
            )
        )

        first = build_reconciliation_alert(report)
        second = build_reconciliation_alert(report)

        self.assertEqual(first["severity"], "critical")
        self.assertEqual(first["dedupe_key"], second["dedupe_key"])
        self.assertEqual(first["incident"]["totals"]["missing_files"], 1)
        self.assertEqual(
            first["incident"]["affected_tenants"][0]["tenant_id"], str(tenant_id)
        )

    @override_settings(
        OPERATIONS_ALERT_WEBHOOK_URL="https://alerts.example.test/hook",
        OPERATIONS_ALERT_WEBHOOK_SECRET="test-signing-secret",
        OPERATIONS_ALERT_TIMEOUT_SECONDS=7,
        OPERATIONS_ALERT_COOLDOWN_SECONDS=3600,
    )
    def test_webhook_is_signed_and_persists_cooldown_after_success(self):
        payload = {
            "event": "map_reconciliation_failed",
            "severity": "critical",
            "dedupe_key": "incident-1",
        }
        redis_client = FakeRedis()
        response = Mock()
        response.status_code = 204
        response.raise_for_status.return_value = None
        http_post = Mock(return_value=response)

        delivery = deliver_operations_alert(
            payload,
            redis_client=redis_client,
            http_post=http_post,
        )

        self.assertEqual(delivery.status, "delivered")
        request = http_post.call_args
        body = request.kwargs["data"]
        expected_signature = hmac.new(
            b"test-signing-secret", body, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            request.kwargs["headers"]["X-Delta-Mapas-Signature"],
            f"sha256={expected_signature}",
        )
        self.assertEqual(request.kwargs["timeout"], 7)
        self.assertFalse(request.kwargs["allow_redirects"])
        self.assertEqual(redis_client.saved[2], 3600)

    @override_settings(
        OPERATIONS_ALERT_WEBHOOK_URL="https://alerts.example.test/hook",
        OPERATIONS_ALERT_WEBHOOK_SECRET="",
    )
    def test_duplicate_alert_is_suppressed_without_http_request(self):
        http_post = Mock()

        delivery = deliver_operations_alert(
            {"event": "test", "dedupe_key": "same-incident"},
            redis_client=FakeRedis(duplicate=True),
            http_post=http_post,
        )

        self.assertEqual(delivery.status, "suppressed")
        http_post.assert_not_called()

    @override_settings(
        OPERATIONS_ALERT_WEBHOOK_URL="http://alerts.example.test/hook",
        OPERATIONS_ALERT_ALLOW_INSECURE_HTTP=False,
    )
    def test_plain_http_webhook_is_rejected(self):
        delivery = deliver_operations_alert(
            {"event": "test", "dedupe_key": "incident"},
            redis_client=FakeRedis(),
        )

        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.error, "webhook_url_must_use_https")

    @patch("apps.maps.tasks.deliver_operations_alert")
    @patch("apps.maps.tasks.run_reconciliation")
    def test_celery_task_returns_totals_and_delivery_status(self, run, deliver):
        run.return_value = batch_report(
            TenantReconciliationResult(
                tenant_id=uuid4(),
                schema_name="principal",
                stalled_candidates=1,
                expired_jobs=1,
            )
        )
        deliver.return_value = AlertDelivery(attempted=True, delivered=True)

        result = reconcile_all_tenants.run()

        self.assertEqual(result["status"], "issues")
        self.assertEqual(result["totals"]["expired_jobs"], 1)
        self.assertEqual(result["alert_delivery"], "delivered")
