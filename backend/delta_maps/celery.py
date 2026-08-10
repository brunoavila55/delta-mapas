import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "delta_maps.settings")

app = Celery("delta_maps")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
