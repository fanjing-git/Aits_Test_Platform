"""Routes for account registration and JWT authentication."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import (
    CurrentUserView,
    LoginView,
    RegisterView,
    UserManagementDetailView,
    UserManagementListView,
    UserActionRevokeView,
    UserInvitationResendView,
    UserPasswordResetLinkView,
    AccountActivationView,
    AccountAuditEventListView,
    BootstrapAdminView,
    BootstrapStatusView,
    PasswordResetView,
)

app_name = "users"

urlpatterns = [
    path("bootstrap/status/", BootstrapStatusView.as_view(), name="bootstrap-status"),
    path("bootstrap/", BootstrapAdminView.as_view(), name="bootstrap-admin"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path("activate/", AccountActivationView.as_view(), name="activate-account"),
    path("password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path("audit-events/", AccountAuditEventListView.as_view(), name="account-audit-events"),
    path("users/", UserManagementListView.as_view(), name="user-management-list"),
    path(
        "users/<int:pk>/",
        UserManagementDetailView.as_view(),
        name="user-management-detail",
    ),
    path(
        "users/<int:pk>/resend-invitation/",
        UserInvitationResendView.as_view(),
        name="user-invitation-resend",
    ),
    path(
        "users/<int:pk>/password-reset-link/",
        UserPasswordResetLinkView.as_view(),
        name="user-password-reset-link",
    ),
    path(
        "users/<int:pk>/revoke-actions/",
        UserActionRevokeView.as_view(),
        name="user-action-revoke",
    ),
]
