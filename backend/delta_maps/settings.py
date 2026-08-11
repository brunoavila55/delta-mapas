from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

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


SECRET_KEY = env(
    "DJANGO_SECRET_KEY", "unsafe-development-key-change-me-at-least-32-bytes"
)
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8000")
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

SHARED_APPS = (
    "django_tenants",
    "apps.tenants",
    "apps.accounts",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
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
    "corsheaders.middleware.CorsMiddleware",
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
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "delta_maps.pagination.DeltaPageNumberPagination",
    "PAGE_SIZE": int(env("API_PAGE_SIZE", "20")),
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Delta Mapas API",
    "DESCRIPTION": "API multitenant para produtos de sensoriamento remoto.",
    "VERSION": "1.0.0",
}

CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(env("CELERY_TASK_TIME_LIMIT", "3600"))
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_TASK_SOFT_TIME_LIMIT", "3300"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

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
COPERNICUS_AUTH_TIMEOUT_SECONDS = float(env("COPERNICUS_AUTH_TIMEOUT_SECONDS", "30"))
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
MAX_PROPERTY_AREA_HECTARES = float(env("MAX_PROPERTY_AREA_HECTARES", "0"))
MAP_MAX_DATE_RANGE_DAYS = int(env("MAP_MAX_DATE_RANGE_DAYS", "0"))
DATA_UPLOAD_MAX_MEMORY_SIZE = SHAPEFILE_MAX_UPLOAD_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)

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
