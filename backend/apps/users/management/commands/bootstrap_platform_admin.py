"""Create the explicitly configured platform administrator without resets."""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.users.models import UserProfile
from apps.users.services import BootstrapConflict, bootstrap_platform_admin

User = get_user_model()


class Command(BaseCommand):
    """Ensure one configured administrator exists without changing existing users."""

    help = "Create the configured platform administrator once; never reset an account."

    def add_arguments(self, parser) -> None:
        """Allow deployment to override the username while keeping the password out of argv."""
        parser.add_argument(
            "--username",
            default=os.environ.get("AITS_BOOTSTRAP_ADMIN_USERNAME", "platform_admin"),
            help="Initial administrator username; defaults to the deployment environment value.",
        )
        parser.add_argument(
            "--allow-unconfigured",
            action="store_true",
            help="Keep the service available for the first-run web setup when no password is configured.",
        )

    def handle(self, *args: object, **options: object) -> str:
        """Create the configured administrator or safely report that no change is needed."""
        del args
        username = str(options["username"]).strip()
        password = os.environ.get("AITS_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not username:
            raise CommandError("AITS_BOOTSTRAP_ADMIN_USERNAME must not be empty.")

        try:
            if not password:
                existing = User.objects.filter(username__iexact=username).select_related("profile").first()
                if existing is not None and existing.is_active and existing.profile.role == UserProfile.Role.ADMIN:
                    message = f"Bootstrap skipped: administrator '{existing.get_username()}' already exists."
                    self.stdout.write(self.style.SUCCESS(message))
                    return message
                if User.objects.filter(is_active=True, profile__role=UserProfile.Role.ADMIN).exists():
                    message = "Bootstrap skipped: an active administrator already exists; no account was changed."
                    self.stdout.write(self.style.SUCCESS(message))
                    return message
                if options["allow_unconfigured"]:
                    message = "Bootstrap pending: no administrator configured; first-run setup remains available."
                    self.stdout.write(self.style.WARNING(message))
                    return message
                raise CommandError(
                    "No active administrator exists. Set AITS_BOOTSTRAP_ADMIN_PASSWORD for the first deployment."
                )
            user = bootstrap_platform_admin(
                username=username,
                password=password,
                source="deployment_bootstrap",
                require_empty_platform=False,
            )
        except BootstrapConflict as exc:
            raise CommandError(str(exc)) from exc

        message = f"Bootstrap ensured platform administrator '{user.get_username()}'."
        self.stdout.write(self.style.SUCCESS(message))
        return message
