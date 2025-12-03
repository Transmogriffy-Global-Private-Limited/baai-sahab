from django.urls import path
from . import views

urlpatterns = [
    # Seeker → find helpers
    path("helpers/", views.seeker_matches_view, name="match-helpers"),

    # Helper → find seekers
    path("seekers/", views.helper_matches_view, name="match-seekers"),
]
