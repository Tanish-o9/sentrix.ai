from django.urls import path, include
from sentrix_backend.views import dashboard_view

urlpatterns = [
    path("", dashboard_view, name="root-dashboard"),
    path("api/", include("sentrix_backend.urls")),
]
