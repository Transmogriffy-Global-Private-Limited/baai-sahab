from django.urls import path
from . import views

urlpatterns = [
    # Upload / replace own profile picture
    path("profile-picture/", views.upload_profile_picture_view, name="media-upload-profile-picture"),

    # Publicly fetch a user's profile picture by their user_id
    path(
        "profile-picture/<uuid:user_id>/",
        views.get_profile_picture_view,
        name="media-get-profile-picture",
    ),
]
