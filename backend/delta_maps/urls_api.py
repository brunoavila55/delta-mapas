from django.urls import include, path
from rest_framework.routers import DefaultRouter

from delta_maps.views import health
from apps.properties.views import PropertyViewSet
from apps.maps.views import MapJobViewSet

router = DefaultRouter()
router.register("properties", PropertyViewSet, basename="property")
router.register("map-jobs", MapJobViewSet, basename="map-job")

urlpatterns = [
    path("health/", health, name="health"),
    path("auth/", include("apps.accounts.urls")),
    path("billing/", include("apps.billing.urls")),
    path("", include(router.urls)),
]
