from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from django.db import connection


class TenantContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.schema_name = getattr(connection, "schema_name", "public")
        return True


class JsonFormatter(logging.Formatter):
    context_fields = (
        "schema_name",
        "tenant_id",
        "job_id",
        "user_id",
        "stac_item_id",
        "celery_task_id",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.context_fields:
            value = getattr(record, field, None)
            if value not in (None, ""):
                payload[field] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
