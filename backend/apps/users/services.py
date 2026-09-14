"""Account invitation, password reset and one-time token services."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.users.models import (
    AccountActionToken,
    AccountAuditEvent,
    PlatformBootstrapState,
    UserProfile,
)

User = get_user_model()


class InvalidAccountActionToken(ValueError):
    """Raised when an account action token is missing, expired or already used."""


class BootstrapConflict(ValueError):
    """Raised when first-run administrator setup is already closed or collides."""


def record_audit_event(
    *,
    event: str,
    target: User,
    actor: User | None,
    metadata: dict[str, object] | None = None,
) -> AccountAuditEvent:
    """Persist redacted account evidence without accepting secrets in metadata."""
    safe_metadata = {
        str(key): value
        for key, value in (metadata or {}).items()
        if key not in {"token", "password", "api_key", "secret"}
    }
    return AccountAuditEvent.objects.create(
        actor=actor,
        target=target,
        target_username=target.get_username(),
        event=event,
        metadata=safe_metadata,
    )


def _hash_token(raw_token: str) -> str:
    """Return a non-reversible digest suitable for database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_action_token(
    user: User,
    kind: str,
    *,
    created_by: User | None,
    lifetime_hours: int = 72,
) -> tuple[str, AccountActionToken]:
    """Issue a fresh one-time token and invalidate previous tokens of that kind."""
    now = timezone.now()
    raw_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        AccountActionToken.objects.filter(
            user=user,
            kind=kind,
            used_at__isnull=True,
        ).update(used_at=now)
        token = AccountActionToken.objects.create(
            user=user,
            created_by=created_by,
            kind=kind,
            token_hash=_hash_token(raw_token),
            expires_at=now + timedelta(hours=lifetime_hours),
        )
    return raw_token, token


def get_valid_action_token(raw_token: str, kind: str) -> AccountActionToken:
    """Resolve a token without consuming it so password validation can run first."""
    if not raw_token or len(raw_token) > 256:
        raise InvalidAccountActionToken("账号操作链接无效或已过期。")
    token = (
        AccountActionToken.objects.select_related("user")
        .filter(token_hash=_hash_token(raw_token), kind=kind)
        .first()
    )
    if token is None or token.used_at is not None or token.expires_at <= timezone.now():
        raise InvalidAccountActionToken("账号操作链接无效或已过期。")
    return token


def consume_action_token(raw_token: str, kind: str) -> AccountActionToken:
    """Atomically consume a valid token, preventing replay under concurrent requests."""
    with transaction.atomic():
        token = (
            AccountActionToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash_token(raw_token), kind=kind)
            .first()
        )
        if token is None or token.used_at is not None or token.expires_at <= timezone.now():
            raise InvalidAccountActionToken("账号操作链接无效或已过期。")
        token.used_at = timezone.now()
        token.save(update_fields=("used_at",))
        return token


def revoke_action_tokens(user: User, kind: str | None = None) -> int:
    """Revoke outstanding account action tokens and return the affected count."""
    filters = {"user": user, "used_at__isnull": True}
    if kind:
        filters["kind"] = kind
    return AccountActionToken.objects.filter(**filters).update(used_at=timezone.now())


@transaction.atomic
def bootstrap_platform_admin(
    *,
    username: str,
    password: str,
    source: str,
    require_empty_platform: bool = True,
) -> User:
    """Create one administrator safely without resetting any existing account."""
    normalized_username = username.strip()
    if not normalized_username:
        raise BootstrapConflict("Administrator username is required.")

    state, _created = PlatformBootstrapState.objects.select_for_update().get_or_create(
        singleton_key=1,
    )
    active_admin_exists = User.objects.filter(
        is_active=True,
        profile__role=UserProfile.Role.ADMIN,
    ).exists()
    if require_empty_platform and (state.completed_at is not None or active_admin_exists):
        raise BootstrapConflict("Platform administrator setup has already been completed.")

    existing = User.objects.filter(username__iexact=normalized_username).first()
    if existing is not None:
        try:
            existing_role = existing.profile.role
        except UserProfile.DoesNotExist:
            existing_role = None
        if existing.is_active and existing_role == UserProfile.Role.ADMIN:
            state.completed_at = state.completed_at or timezone.now()
            state.save(update_fields=("completed_at",))
            return existing
        raise BootstrapConflict("The requested administrator username is already in use.")

    candidate = User(username=normalized_username, is_active=True)
    try:
        validate_password(password, user=candidate)
    except ValidationError as exc:
        raise BootstrapConflict("The administrator password does not meet password policy.") from exc

    user = User.objects.create_user(
        username=normalized_username,
        password=password,
        is_active=True,
    )
    user.profile.role = UserProfile.Role.ADMIN
    user.profile.save(update_fields=("role", "updated_at"))
    state.completed_at = timezone.now()
    state.save(update_fields=("completed_at",))
    record_audit_event(
        event=AccountAuditEvent.Event.ACCOUNT_UPDATED,
        target=user,
        actor=None,
        metadata={"source": source, "role": UserProfile.Role.ADMIN},
    )
    return user


@transaction.atomic
def invite_user(
    *,
    username: str,
    email: str,
    role: str,
    created_by: User,
    lifetime_hours: int,
) -> tuple[User, str, AccountActionToken]:
    """Create an inactive least-privilege account and issue its activation token."""
    user = User.objects.create(username=username, email=email, is_active=False)
    user.set_unusable_password()
    user.save(update_fields=("password", "is_active"))
    user.profile.role = role or UserProfile.Role.VIEWER
    user.profile.save(update_fields=("role", "updated_at"))
    raw_token, token = create_action_token(
        user,
        AccountActionToken.Kind.INVITATION,
        created_by=created_by,
        lifetime_hours=lifetime_hours,
    )
    return user, raw_token, token


@transaction.atomic
def activate_user(raw_token: str, password: str) -> User:
    """Consume an invitation and activate the account with a user-chosen password."""
    token = consume_action_token(raw_token, AccountActionToken.Kind.INVITATION)
    user = User.objects.select_for_update().get(pk=token.user_id)
    user.set_password(password)
    user.is_active = True
    user.save(update_fields=("password", "is_active"))
    record_audit_event(
        event=AccountAuditEvent.Event.ACTIVATED,
        target=user,
        actor=None,
    )
    return user


@transaction.atomic
def reset_user_password(raw_token: str, password: str) -> User:
    """Consume a password-reset token and replace the target password."""
    token = consume_action_token(raw_token, AccountActionToken.Kind.PASSWORD_RESET)
    user = User.objects.select_for_update().get(pk=token.user_id)
    user.set_password(password)
    user.save(update_fields=("password",))
    record_audit_event(
        event=AccountAuditEvent.Event.PASSWORD_RESET,
        target=user,
        actor=None,
    )
    return user
