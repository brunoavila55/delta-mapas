from django.urls import path

from .views import auth, billing, jobs, maps, properties

app_name = "web"

urlpatterns = [
    path("login/", auth.login_view, name="login"),
    path("logout/", auth.logout_view, name="logout"),
    path("", auth.dashboard, name="dashboard"),
    path("properties/", properties.properties, name="properties"),
    path("properties/new/", properties.property_form, name="property_create"),
    path("properties/<uuid:pk>/edit/", properties.property_form, name="property_edit"),
    path(
        "properties/<uuid:pk>/delete/",
        properties.property_delete,
        name="property_delete",
    ),
    path("jobs/", jobs.jobs, name="jobs"),
    path("jobs/new/", jobs.job_create, name="job_create"),
    path("jobs/<uuid:pk>/cancel/", jobs.job_cancel, name="job_cancel"),
    path("jobs/<uuid:pk>/reprocess/", jobs.job_reprocess, name="job_reprocess"),
    path("maps/", maps.maps, name="maps"),
    path("maps/<uuid:pk>/<str:file_format>/", maps.map_file, name="map_file"),
    path("billing/", billing.billing, name="billing"),
]
