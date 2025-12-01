from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="auth-signup"),
    path("signin/", views.signin_view, name="auth-signin"),
    path("logout/", views.logout_view, name="auth-logout"),
]
