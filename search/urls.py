from django.urls import path
from . import views

urlpatterns = [
    path("helpers/", views.search_helpers_view, name="search-helpers"),
    path("seekers/", views.search_seekers_view, name="search-seekers"),
]
