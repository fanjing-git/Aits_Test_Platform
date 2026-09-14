"""Django Admin integration for user profiles."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.users.models import AccountActionToken, AccountAuditEvent, UserProfile

User = get_user_model()


class UserProfileInline(admin.StackedInline):
    """Edit a user's platform profile from the built-in user page."""

    model = UserProfile
    can_delete = False
    extra = 0
    fields = ("role", "preferences", "notification_preferences")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Provide direct searching and filtering for user profiles."""

    list_display = ("user", "role", "updated_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Extend Django's user editor with the platform profile inline."""

    inlines = (*DjangoUserAdmin.inlines, UserProfileInline)


@admin.register(AccountAuditEvent)
class AccountAuditEventAdmin(admin.ModelAdmin):
    """Keep account audit evidence visible but immutable in Django Admin."""

    list_display = ("created_at", "event", "target_username", "actor", "metadata")
    list_filter = ("event",)
    search_fields = ("target_username", "actor__username")
    readonly_fields = tuple(field.name for field in AccountAuditEvent._meta.fields)

    def has_add_permission(self, request: object) -> bool:
        """Disallow manual audit records."""
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        """Disallow audit tampering."""
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        """Retain audit evidence permanently."""
        return False


@admin.register(AccountActionToken)
class AccountActionTokenAdmin(admin.ModelAdmin):
    """Expose token state for operations without exposing raw token values."""

    list_display = ("user", "kind", "expires_at", "used_at", "created_at")
    list_filter = ("kind", "used_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = tuple(field.name for field in AccountActionToken._meta.fields)

    def has_add_permission(self, request: object) -> bool:
        """Tokens must only be issued through the service layer."""
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        """Token state must only change through lifecycle operations."""
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        """Retain token lifecycle evidence."""
        return False
