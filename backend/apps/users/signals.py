"""Signal handlers that keep user profiles in sync with users."""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import UserProfile


@receiver(post_save, sender=get_user_model())
def create_profile_for_new_user(
    sender: type,
    instance: object,
    created: bool,
    **kwargs: object,
) -> None:
    """Create the default profile exactly once for each new user."""
    del sender, kwargs
    if created:
        UserProfile.objects.create(user=instance)
