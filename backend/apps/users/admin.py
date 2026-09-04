"""Django Admin integration for user profiles."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.users.models import UserProfile

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
