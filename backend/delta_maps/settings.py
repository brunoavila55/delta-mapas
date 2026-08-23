from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
_unsafe_development_key = "unsafe-development-key-change-me-at-least-32-bytes"
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    _unsafe_development_key if DEBUG else None,
)
if not DEBUG and (len(SECRET_KEY) < 32 or SECRET_KEY == _unsafe_development_key):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a unique value of at least 32 characters outside development."
    )
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8000")

SHARED_APPS = (
    "django_tenants",
    "apps.tenants",
    "apps.accounts",
    "apps.web",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",
)

TENANT_APPS = (
    "apps.properties",
    "apps.maps",
    "apps.billing",
)

INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.middleware.security.SecurityMiddleware",
]
if not DEBUG:
    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")
MIDDLEWARE += [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "delta_maps.urls"
PUBLIC_SCHEMA_URLCONF = "delta_maps.urls_public"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "delta_maps.wsgi.application"
ASGI_APPLICATION = "delta_maps.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": env("POSTGRES_DB", "delta_maps"),
        "USER": env("POSTGRES_USER", "delta_maps"),
        "PASSWORD": env("POSTGRES_PASSWORD", "delta_maps"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
    }
}
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)
ORIGINAL_BACKEND = "django.contrib.gis.db.backends.postgis"

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"
SHOW_PUBLIC_IF_NO_TENANT_FOUND = env_bool("SHOW_PUBLIC_IF_NO_TENANT_FOUND", DEBUG)
TENANT_LIMIT_SET_CALLS = True
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
STATICFILES_BACKEND = env(
    "DJANGO_STATICFILES_BACKEND",
    (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    ),
)

if env_bool("MINIO_STORAGE_ENABLED", False):
    minio_scheme = "https" if env_bool("MINIO_USE_SSL", False) else "http"
    minio_endpoint = env("MINIO_ENDPOINT", "localhost:9000")
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": env("MINIO_ACCESS_KEY", "minioadmin"),
                "secret_key": env("MINIO_SECRET_KEY", "minioadmin"),
                "bucket_name": env("MINIO_BUCKET", "delta-mapas"),
                "endpoint_url": f"{minio_scheme}://{minio_endpoint}",
                "region_name": env("MINIO_REGION", "us-east-1"),
                "addressing_style": "path",
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": STATICFILES_BACKEND},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": STATICFILES_BACKEND},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_IP_THROTTLE_RATE = env("LOGIN_IP_THROTTLE_RATE", "20/min")
LOGIN_ACCOUNT_THROTTLE_RATE = env("LOGIN_ACCOUNT_THROTTLE_RATE", "5/min")

_cache_url = env("DJANGO_CACHE_URL", "").strip()
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _cache_url,
        }
        if _cache_url
        else {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "delta-mapas-local",
        }
    )
}
CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(env("CELERY_TASK_TIME_LIMIT", "3600"))
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_TASK_SOFT_TIME_LIMIT", "3300"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
MAP_RECONCILIATION_ENABLED = env_bool("MAP_RECONCILIATION_ENABLED", False)
MAP_RECONCILIATION_INTERVAL_SECONDS = int(
    env("MAP_RECONCILIATION_INTERVAL_SECONDS", "900")
)
MAP_RECONCILIATION_APPLY_STALLED = env_bool("MAP_RECONCILIATION_APPLY_STALLED", True)
MAP_RECONCILIATION_DELETE_ORPHANS = env_bool("MAP_RECONCILIATION_DELETE_ORPHANS", False)
MAP_RECONCILIATION_LOCK_ID = int(env("MAP_RECONCILIATION_LOCK_ID", "7312042026"))
OPERATIONS_ALERT_WEBHOOK_URL = env("OPERATIONS_ALERT_WEBHOOK_URL", "").strip()
OPERATIONS_ALERT_WEBHOOK_SECRET = env("OPERATIONS_ALERT_WEBHOOK_SECRET", "").strip()
OPERATIONS_ALERT_TIMEOUT_SECONDS = float(env("OPERATIONS_ALERT_TIMEOUT_SECONDS", "10"))
OPERATIONS_ALERT_COOLDOWN_SECONDS = int(
    env("OPERATIONS_ALERT_COOLDOWN_SECONDS", "21600")
)
OPERATIONS_ALERT_ALLOW_INSECURE_HTTP = env_bool(
    "OPERATIONS_ALERT_ALLOW_INSECURE_HTTP", False
)

if MAP_RECONCILIATION_INTERVAL_SECONDS <= 0:
    raise ImproperlyConfigured("MAP_RECONCILIATION_INTERVAL_SECONDS must be positive.")
if OPERATIONS_ALERT_TIMEOUT_SECONDS <= 0:
    raise ImproperlyConfigured("OPERATIONS_ALERT_TIMEOUT_SECONDS must be positive.")
if OPERATIONS_ALERT_COOLDOWN_SECONDS <= 0:
    raise ImproperlyConfigured("OPERATIONS_ALERT_COOLDOWN_SECONDS must be positive.")
if not -(2**63) <= MAP_RECONCILIATION_LOCK_ID < 2**63:
    raise ImproperlyConfigured("MAP_RECONCILIATION_LOCK_ID must fit a signed bigint.")

CELERY_BEAT_SCHEDULE = {}
if MAP_RECONCILIATION_ENABLED:
    CELERY_BEAT_SCHEDULE["maps-reconcile-all-tenants"] = {
        "task": "maps.reconcile_all_tenants",
        "schedule": MAP_RECONCILIATION_INTERVAL_SECONDS,
        "options": {"expires": MAP_RECONCILIATION_INTERVAL_SECONDS},
    }

COPERNICUS_STAC_URL = env(
    "COPERNICUS_STAC_URL", "https://stac.dataspace.copernicus.eu/v1/"
)
COPERNICUS_STAC_COLLECTION = env("COPERNICUS_STAC_COLLECTION", "sentinel-2-l2a")
COPERNICUS_STAC_TIMEOUT_SECONDS = float(env("COPERNICUS_STAC_TIMEOUT_SECONDS", "30"))
COPERNICUS_STAC_MAX_ITEMS = int(env("COPERNICUS_STAC_MAX_ITEMS", "100"))
COPERNICUS_STAC_MAX_RETRIES = int(env("COPERNICUS_STAC_MAX_RETRIES", "2"))
COPERNICUS_STAC_RETRY_DELAY_SECONDS = int(
    env("COPERNICUS_STAC_RETRY_DELAY_SECONDS", "15")
)
COPERNICUS_CLIENT_ID = env("COPERNICUS_CLIENT_ID", "").strip()
COPERNICUS_CLIENT_SECRET = env("COPERNICUS_CLIENT_SECRET", "").strip()
COPERNICUS_TOKEN_URL = env(
    "COPERNICUS_TOKEN_URL",
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
)
COPERNICUS_PROCESS_URL = env(
    "COPERNICUS_PROCESS_URL", "https://sh.dataspace.copernicus.eu/process/v1"
)
for _name, _url in (
    ("COPERNICUS_TOKEN_URL", COPERNICUS_TOKEN_URL),
    ("COPERNICUS_PROCESS_URL", COPERNICUS_PROCESS_URL),
):
    _parsed_url = urlparse(_url)
    if (
        _parsed_url.scheme != "https"
        or not _parsed_url.hostname
        or _parsed_url.username
        or _parsed_url.password
    ):
        raise ImproperlyConfigured(
            f"{_name} must be an HTTPS URL without embedded credentials."
        )
COPERNICUS_AUTH_TIMEOUT_SECONDS = float(env("COPERNICUS_AUTH_TIMEOUT_SECONDS", "30"))
COPERNICUS_AUTH_MAX_RESPONSE_BYTES = int(
    env("COPERNICUS_AUTH_MAX_RESPONSE_BYTES", str(64 * 1024))
)
COPERNICUS_PROCESS_TIMEOUT_SECONDS = float(
    env("COPERNICUS_PROCESS_TIMEOUT_SECONDS", "300")
)
COPERNICUS_TOKEN_REFRESH_LEEWAY_SECONDS = int(
    env("COPERNICUS_TOKEN_REFRESH_LEEWAY_SECONDS", "60")
)
COPERNICUS_PROCESS_MAX_RETRIES = int(env("COPERNICUS_PROCESS_MAX_RETRIES", "2"))
COPERNICUS_PROCESS_RETRY_DELAY_SECONDS = int(
    env("COPERNICUS_PROCESS_RETRY_DELAY_SECONDS", "30")
)
COPERNICUS_OUTPUT_RESOLUTION_METERS = float(
    env("COPERNICUS_OUTPUT_RESOLUTION_METERS", "10")
)
COPERNICUS_MAX_OUTPUT_PIXELS = int(env("COPERNICUS_MAX_OUTPUT_PIXELS", "25000000"))
COPERNICUS_MAX_DOWNLOAD_BYTES = int(
    env("COPERNICUS_MAX_DOWNLOAD_BYTES", str(512 * 1024 * 1024))
)
COPERNICUS_SCENE_TIME_TOLERANCE_SECONDS = int(
    env("COPERNICUS_SCENE_TIME_TOLERANCE_SECONDS", "300")
)
COPERNICUS_STAC_MAX_RESPONSE_BYTES = int(
    env("COPERNICUS_STAC_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024))
)
COPERNICUS_STAC_MAX_TOTAL_BYTES = int(
    env("COPERNICUS_STAC_MAX_TOTAL_BYTES", str(8 * 1024 * 1024))
)
MAP_RENDER_MAX_DIMENSION_PIXELS = int(env("MAP_RENDER_MAX_DIMENSION_PIXELS", "2400"))
MAP_RENDER_PNG_DPI = int(env("MAP_RENDER_PNG_DPI", "180"))
MAP_RENDER_PDF_DPI = int(env("MAP_RENDER_PDF_DPI", "150"))
MAP_JOB_STALE_MINUTES = int(env("MAP_JOB_STALE_MINUTES", "120"))

SHAPEFILE_MAX_UPLOAD_BYTES = int(
    env("SHAPEFILE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
)
SHAPEFILE_MAX_UNCOMPRESSED_BYTES = int(
    env("SHAPEFILE_MAX_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024))
)
SHAPEFILE_MAX_FILES = int(env("SHAPEFILE_MAX_FILES", "100"))
SHAPEFILE_MAX_FEATURES = int(env("SHAPEFILE_MAX_FEATURES", "10000"))
SHAPEFILE_MAX_COMPRESSION_RATIO = int(env("SHAPEFILE_MAX_COMPRESSION_RATIO", "200"))
GEOMETRY_MAX_COORDINATES = int(env("GEOMETRY_MAX_COORDINATES", "100000"))
GEOMETRY_MAX_COMPONENTS = int(env("GEOMETRY_MAX_COMPONENTS", "1000"))
GEOMETRY_MAX_NESTING_DEPTH = int(env("GEOMETRY_MAX_NESTING_DEPTH", "8"))
MAX_PROPERTY_AREA_HECTARES = float(env("MAX_PROPERTY_AREA_HECTARES", "0"))
MAP_MAX_DATE_RANGE_DAYS = int(env("MAP_MAX_DATE_RANGE_DAYS", "0"))
DATA_UPLOAD_MAX_MEMORY_SIZE = SHAPEFILE_MAX_UPLOAD_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DJANGO_TRUST_PROXY_HEADERS = env_bool("DJANGO_TRUST_PROXY_HEADERS", False)
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if DJANGO_TRUST_PROXY_HEADERS else None
)
USE_X_FORWARDED_HOST = DJANGO_TRUST_PROXY_HEADERS
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "tenant_context": {"()": "delta_maps.logging.TenantContextFilter"},
    },
    "formatters": {
        "json": {"()": "delta_maps.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["tenant_context"],
        }
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
