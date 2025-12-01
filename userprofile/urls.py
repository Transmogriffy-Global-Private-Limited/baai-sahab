from django.urls import path
from . import views

urlpatterns = [
    # Admin-only service management
    path("admin/services/", views.admin_services_view, name="profile-admin-services"),

    # Helper capability
    path("helper/", views.helper_profile_view, name="profile-helper"),

    # Seeker preferences / requirements
    path("seeker/", views.seeker_prefs_view, name="profile-seeker"),
]
