"""Authentication API views."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.serializers import (
    AccountActionSerializer,
    AccountAuditEventSerializer,
    AdminInvitationSerializer,
    AccountTokenObtainPairSerializer,
    BootstrapAdminSerializer,
    RegistrationSerializer,
    UserSerializer,
    UserManagementSerializer,
)
from apps.users.permissions import IsAdminRole
from apps.users.models import AccountActionToken, AccountAuditEvent, UserProfile
from apps.users.services import (
    BootstrapConflict,
    bootstrap_platform_admin,
    create_action_token,
    record_audit_event,
    revoke_action_tokens,
)

User = get_user_model()


class BootstrapStatusView(APIView):
    """Report whether the one-time platform administrator setup is available."""

    permission_classes = (permissions.AllowAny,)

    def get(self, request: Request) -> Response:
        """Return setup state without exposing users, credentials, or database details."""
        del request
        setup_required = not User.objects.filter(
            is_active=True,
            profile__role=UserProfile.Role.ADMIN,
        ).exists()
        return Response({"setup_required": setup_required})


class BootstrapAdminView(APIView):
    """Create the first platform administrator from the public setup page."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        """Create an administrator once and return safe account details."""
        serializer = BootstrapAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = bootstrap_platform_admin(
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
                source="first_run_setup",
            )
        except BootstrapConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class RegisterView(generics.CreateAPIView):
    """Create a platform account with a default viewer profile."""

    serializer_class = RegistrationSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return public user details after successful registration."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Authenticate an account by username or email and return JWT tokens."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        """Validate credentials and issue an access/refresh token pair."""
        serializer = AccountTokenObtainPairSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        update_last_login(None, serializer.user)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """Return details for the user represented by the access token."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request: Request) -> Response:
        """Serialize the authenticated user without sensitive fields."""
        return Response(UserSerializer(request.user).data)


class UserManagementListView(generics.ListAPIView):
    """List platform accounts for administrators without sensitive fields."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)
    serializer_class = UserManagementSerializer
    queryset = User.objects.select_related("profile").prefetch_related(
        "account_action_tokens"
    ).order_by("username")

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create an inactive account and return a one-time activation path."""
        serializer = AdminInvitationSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        record_audit_event(
            event=AccountAuditEvent.Event.INVITED,
            target=result["user"],
            actor=request.user,
            metadata={"role": result["user"].profile.role},
        )
        return Response(
            {
                "user": UserManagementSerializer(result["user"]).data,
                "activation_path": f"/activate?token={result['raw_token']}",
                "expires_at": result["token"].expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class UserManagementDetailView(generics.RetrieveUpdateAPIView):
    """Allow administrators to update role and active state only."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)
    serializer_class = UserManagementSerializer
    queryset = User.objects.select_related("profile").prefetch_related(
        "account_action_tokens"
    ).all()
    http_method_names = ("get", "patch", "head", "options")

    def perform_update(self, serializer: UserManagementSerializer) -> None:
        """Persist an audit event containing only changed safe account fields."""
        instance = serializer.instance
        before = {
            "role": instance.profile.role,
            "is_active": instance.is_active,
        }
        updated = serializer.save()
        after = {
            "role": updated.profile.role,
            "is_active": updated.is_active,
        }
        changes = {
            field: {"from": before[field], "to": after[field]}
            for field in before
            if before[field] != after[field]
        }
        if changes:
            record_audit_event(
                event=AccountAuditEvent.Event.ACCOUNT_UPDATED,
                target=updated,
                actor=self.request.user,
                metadata={"changes": changes},
            )


class UserInvitationResendView(APIView):
    """Reissue activation links only for inactive accounts."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)

    def post(self, request: Request, pk: int) -> Response:
        """Invalidate prior invitations and issue a fresh activation path."""
        user = get_object_or_404(User.objects.select_related("profile"), pk=pk)
        if user.is_active:
            return Response(
                {"detail": "启用中的账号不需要激活邀请，请使用密码重置。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_token, token = create_action_token(
            user,
            AccountActionToken.Kind.INVITATION,
            created_by=request.user,
        )
        record_audit_event(
            event=AccountAuditEvent.Event.INVITATION_RESENT,
            target=user,
            actor=request.user,
        )
        return Response(
            {
                "user": UserManagementSerializer(user).data,
                "activation_path": f"/activate?token={raw_token}",
                "expires_at": token.expires_at,
            },
            status=status.HTTP_200_OK,
        )


class UserPasswordResetLinkView(APIView):
    """Issue a one-time password reset link for an account."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)

    def post(self, request: Request, pk: int) -> Response:
        """Return a reset path without exposing passwords or token digests."""
        user = get_object_or_404(User.objects.select_related("profile"), pk=pk)
        if not user.is_active:
            return Response(
                {"detail": "账号尚未激活，请先重发激活邀请。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_token, token = create_action_token(
            user,
            AccountActionToken.Kind.PASSWORD_RESET,
            created_by=request.user,
        )
        record_audit_event(
            event=AccountAuditEvent.Event.PASSWORD_RESET_ISSUED,
            target=user,
            actor=request.user,
        )
        return Response(
            {
                "user": UserManagementSerializer(user).data,
                "reset_path": f"/reset-password?token={raw_token}",
                "expires_at": token.expires_at,
            },
            status=status.HTTP_200_OK,
        )


class UserActionRevokeView(APIView):
    """Revoke outstanding activation and reset links for one account."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)

    def post(self, request: Request, pk: int) -> Response:
        """Invalidate all outstanding account action links."""
        user = get_object_or_404(User, pk=pk)
        revoked = revoke_action_tokens(user)
        record_audit_event(
            event=AccountAuditEvent.Event.INVITATION_REVOKED,
            target=user,
            actor=request.user,
            metadata={"revoked_count": revoked},
        )
        return Response({"revoked": revoked}, status=status.HTTP_200_OK)


class AccountAuditEventListView(generics.ListAPIView):
    """List recent account lifecycle events for platform administrators."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)
    serializer_class = AccountAuditEventSerializer
    queryset = AccountAuditEvent.objects.select_related("actor", "target").order_by(
        "-created_at"
    )[:200]


class AccountActivationView(APIView):
    """Public endpoint that activates an invited account exactly once."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        """Set the invited user's password and enable login."""
        serializer = AccountActionSerializer(
            data={**request.data, "action_kind": AccountActionToken.Kind.INVITATION}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"message": "账号已激活，请使用新密码登录。", "user": UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )


class PasswordResetView(APIView):
    """Public endpoint for one-time administrator-issued password links."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        """Replace the target password and invalidate the reset link."""
        serializer = AccountActionSerializer(
            data={**request.data, "action_kind": AccountActionToken.Kind.PASSWORD_RESET}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"message": "密码已重置，请使用新密码登录。", "user": UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )
