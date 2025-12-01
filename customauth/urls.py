from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="auth-signup"),
    path("signin/", views.signin_view, name="auth-signin"),
    path("logout/", views.logout_view, name="auth-logout"),
    path("change-password/", views.change_password_view, name="auth-change-password"),
    path("revoke-all-sessions/", views.revoke_all_sessions_view, name="auth-revoke-all-sessions"),
]
