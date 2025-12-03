from django.urls import path
from . import views

urlpatterns = [
    # Filter helpers by structured criteria
    path("helpers/", views.filter_helpers_view, name="filter-helpers"),

    # Filter seekers by structured criteria
    path("seekers/", views.filter_seekers_view, name="filter-seekers"),
]
