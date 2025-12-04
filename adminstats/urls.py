from django.urls import path
from . import views

urlpatterns = [
    path(
        "seekers-per-service/",
        views.seekers_per_service_view,
        name="adminstats-seekers-per-service",
    ),
    path(
        "summary/",
        views.summary_counts_view,
        name="adminstats-summary",
    ),
    path(
        "registrations/",
        views.registrations_stats_view,
        name="adminstats-registrations",
    ),
]
