"""Routes for account registration and JWT authentication."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import (
    CurrentUserView,
    LoginView,
    RegisterView,
    UserManagementDetailView,
    UserManagementListView,
)

app_name = "users"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path("users/", UserManagementListView.as_view(), name="user-management-list"),
    path(
        "users/<int:pk>/",
        UserManagementDetailView.as_view(),
        name="user-management-detail",
    ),
]
