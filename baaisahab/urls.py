"""
URL configuration for baaisahab project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.static import serve
from django.conf import settings
import os

urlpatterns = [
    # Favicon at /favicon.ico
    path(
        "favicon.ico",
        serve,
        {
            "path": "favicon.ico",
            "document_root": os.path.join(settings.BASE_DIR, "baaisahab", "res"),
        },
    ),

    path("admin/", admin.site.urls),
    path("", include("health.urls")),
    path("auth/", include("customauth.urls")),
    path("profile/", include("userprofile.urls")),
    path("matching/", include("matching.urls")),
    path("media/", include("mediahandling.urls")),
    path("search/" include("search.urls")),
    path("filter/" include ("filter.urls"))
]
