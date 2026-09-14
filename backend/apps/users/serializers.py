"""Serializers for account registration and authenticated user details."""

from typing import Any

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions, serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import AccountActionToken, AccountAuditEvent, UserProfile
from apps.users.services import (
    InvalidAccountActionToken,
    activate_user,
    get_valid_action_token,
    invite_user,
    reset_user_password,
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Expose non-sensitive account and profile information."""

    role = serializers.CharField(source="profile.role", read_only=True)
    preferences = serializers.JSONField(source="profile.preferences", read_only=True)
    notification_preferences = serializers.JSONField(
        source="profile.notification_preferences",
        read_only=True,
    )

    class Meta:
        """Define the public user response fields."""

        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "preferences",
            "notification_preferences",
        )
        read_only_fields = fields


class UserManagementSerializer(serializers.ModelSerializer):
    """Expose safe account status and allow administrators to assign roles."""

    role = serializers.ChoiceField(
        source="profile.role", choices=UserProfile.Role.choices
    )
    role_label = serializers.CharField(source="profile.get_role_display", read_only=True)
    pending_invitation = serializers.SerializerMethodField()
    invitation_expires_at = serializers.SerializerMethodField()
    pending_password_reset = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_label",
            "is_active",
            "date_joined",
            "last_login",
            "pending_invitation",
            "invitation_expires_at",
            "pending_password_reset",
        )
        read_only_fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role_label",
            "date_joined",
            "last_login",
            "pending_invitation",
            "invitation_expires_at",
            "pending_password_reset",
        )

    def _pending_token(self, user: Any, kind: str) -> Any:
        """Return the newest unconsumed token without exposing its digest."""
        return (
            user.account_action_tokens.filter(
                kind=kind,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

    def get_pending_invitation(self, obj: Any) -> bool:
        """Expose whether an inactive account has a usable invitation."""
        token = self._pending_token(obj, AccountActionToken.Kind.INVITATION)
        return bool(token and token.expires_at > timezone.now())

    def get_invitation_expires_at(self, obj: Any) -> Any:
        """Expose only an invitation expiry timestamp, never its secret."""
        token = self._pending_token(obj, AccountActionToken.Kind.INVITATION)
        return token.expires_at if token and token.expires_at > timezone.now() else None

    def get_pending_password_reset(self, obj: Any) -> bool:
        """Expose whether an unused password-reset link exists."""
        token = self._pending_token(obj, AccountActionToken.Kind.PASSWORD_RESET)
        return bool(token and token.expires_at > timezone.now())

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")
        target = self.instance
        requested_role = attrs.get("profile", {}).get("role")
        requested_active = attrs.get("is_active")
        if target is not None and request is not None and target.pk == request.user.pk:
            if requested_role and requested_role != UserProfile.Role.ADMIN:
                other_active_admin_exists = User.objects.filter(
                    is_active=True,
                    profile__role=UserProfile.Role.ADMIN,
                ).exclude(pk=target.pk).exists()
                if not other_active_admin_exists:
                    raise serializers.ValidationError(
                        {"role": "当前账号是最后一个启用中的管理员，请先授权另一名管理员。"}
                    )
            if requested_active is False:
                raise serializers.ValidationError(
                    {"is_active": "不能停用当前登录账号。"}
                )
        return attrs

    @transaction.atomic
    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        profile_data = validated_data.pop("profile", {})
        if "is_active" in validated_data:
            instance.is_active = validated_data["is_active"]
            instance.save(update_fields=("is_active",))
        if "role" in profile_data:
            instance.profile.role = profile_data["role"]
            instance.profile.save(update_fields=("role", "updated_at"))
        return instance


class RegistrationSerializer(serializers.ModelSerializer):
    """Register with either one account identifier or the legacy field pair."""

    account = serializers.CharField(required=False, write_only=True, max_length=254)
    username = serializers.CharField(required=False, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        """Define accepted registration fields."""

        model = User
        fields = ("account", "username", "email", "password", "password_confirm")

    @staticmethod
    def _is_email(value: str) -> bool:
        """Return whether an account identifier is a valid email address."""
        try:
            serializers.EmailField().run_validation(value)
        except serializers.ValidationError:
            return False
        return True

    def validate_email(self, value: str) -> str:
        """Reject duplicate email addresses regardless of letter casing."""
        if not value:
            return value
        normalized_email = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized_email

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Normalize one account value and require matching passwords."""
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )

        account = attrs.pop("account", "").strip()
        username = attrs.get("username", "").strip()
        email = attrs.get("email", "").strip()
        if account:
            if username or email:
                raise serializers.ValidationError(
                    {"account": "Use account alone instead of username or email."}
                )
            if self._is_email(account):
                email = User.objects.normalize_email(account).lower()
                username = email
            else:
                username = account
                email = ""
        elif not username:
            raise serializers.ValidationError(
                {"account": "Enter a username or email address."}
            )

        try:
            User._meta.get_field("username").run_validators(username)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"account": exc.messages}) from exc

        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError(
                {"account": "A user with this account already exists."}
            )
        if email and User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                {"account": "A user with this email already exists."}
            )

        attrs["username"] = username
        attrs["email"] = email
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Any:
        """Create the user through Django's password-hashing manager."""
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        # The profile signal owns creation; this fallback also supports bulk/custom flows.
        UserProfile.objects.get_or_create(user=user)
        return user


class AdminInvitationSerializer(serializers.Serializer):
    """Validate the minimum data required to invite a colleague."""

    account = serializers.CharField(max_length=254)
    role = serializers.ChoiceField(
        choices=UserProfile.Role.choices,
        default=UserProfile.Role.VIEWER,
    )
    expires_in_hours = serializers.IntegerField(
        min_value=1,
        max_value=168,
        default=72,
        required=False,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Normalize a username/email and reject duplicate accounts safely."""
        account = attrs["account"].strip()
        if not account:
            raise serializers.ValidationError({"account": "请输入用户名或邮箱。"})
        if self._is_email(account):
            username = User.objects.normalize_email(account).lower()
            email = username
        else:
            username = account
            email = ""
        try:
            User._meta.get_field("username").run_validators(username)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"account": exc.messages}) from exc
        if User.objects.filter(username__iexact=username).exists() or (
            email and User.objects.filter(email__iexact=email).exists()
        ):
            raise serializers.ValidationError({"account": "该账号已存在，请在用户列表中重发邀请或重置密码。"})
        attrs.update({"username": username, "email": email})
        return attrs

    @staticmethod
    def _is_email(value: str) -> bool:
        """Return whether an identifier is an email address."""
        try:
            serializers.EmailField().run_validation(value)
        except serializers.ValidationError:
            return False
        return True

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """Create an inactive account and return a one-time activation secret."""
        user, raw_token, token = invite_user(
            username=validated_data["username"],
            email=validated_data["email"],
            role=validated_data["role"],
            created_by=self.context["request"].user,
            lifetime_hours=validated_data.get("expires_in_hours", 72),
        )
        return {"user": user, "raw_token": raw_token, "token": token}


class AccountActionSerializer(serializers.Serializer):
    """Validate and consume a one-time activation or reset link."""

    token = serializers.CharField(write_only=True, trim_whitespace=True)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        validators=[validate_password],
    )
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)
    action_kind = serializers.CharField(write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Check token state and password confirmation before consuming anything."""
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "两次输入的密码不一致。"})
        try:
            token = get_valid_action_token(attrs["token"], attrs["action_kind"])
        except InvalidAccountActionToken as exc:
            raise serializers.ValidationError({"token": str(exc)}) from exc
        validate_password(attrs["password"], user=token.user)
        attrs["_user_id"] = token.user_id
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Any:
        """Apply the requested action atomically and invalidate the link."""
        raw_token = validated_data["token"]
        password = validated_data["password"]
        if validated_data["action_kind"] == AccountActionToken.Kind.INVITATION:
            return activate_user(raw_token, password)
        return reset_user_password(raw_token, password)


class AccountAuditEventSerializer(serializers.ModelSerializer):
    """Expose safe account audit evidence to platform administrators."""

    actor_username = serializers.CharField(
        source="actor.username",
        read_only=True,
        default=None,
    )
    event_label = serializers.CharField(source="get_event_display", read_only=True)

    class Meta:
        model = AccountAuditEvent
        fields = (
            "id",
            "event",
            "event_label",
            "actor_username",
            "target_username",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class AccountTokenObtainPairSerializer(serializers.Serializer):
    """Issue JWT tokens after resolving either a username or an email address."""

    account = serializers.CharField(required=False, write_only=True)
    username = serializers.CharField(required=False, write_only=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, str]:
        """Authenticate the resolved active user and return a JWT pair."""
        identifier = (attrs.get("account") or attrs.get("username") or "").strip()
        if not identifier:
            raise serializers.ValidationError(
                {"account": "Enter a username or email address."}
            )

        user = User.objects.filter(username__iexact=identifier).first()
        if user is None:
            user = User.objects.filter(email__iexact=identifier).first()
        authenticated_user = None
        if user is not None:
            authenticated_user = authenticate(
                request=self.context.get("request"),
                username=user.get_username(),
                password=attrs["password"],
            )
        if authenticated_user is None or not authenticated_user.is_active:
            raise exceptions.AuthenticationFailed(
                "No active account found with the given credentials.",
                code="authorization",
            )

        self.user = authenticated_user
        refresh = RefreshToken.for_user(authenticated_user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}
