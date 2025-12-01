import uuid
from django.db import models
from django.contrib.postgres.fields import ArrayField

from customauth.models import User


class UserProfile(models.Model):
    """
    Basic profile info for all users (helper or seeker).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(blank=True)
    bio = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"UserProfile({self.user.phone_number})"


class Service(models.Model):
    """
    Catalog of all services helpers can provide and seekers can request.
    Use slugs for filtering + matching.
    Example: 'cooking', 'cleaning', 'laundry', 'babysitting'
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class HelperProfile(models.Model):
    """
    What a helper CAN do: services, availability, frequency, experience, location.
    Only applies when user.user_type == 'helper'.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="helper_profile",
    )

    # Example: ["cooking", "cleaning", "laundry"]
    services = ArrayField(
        models.CharField(max_length=64),
        default=list,
        help_text="List of services (slugs) this helper can provide",
    )

    city = models.CharField(max_length=128)
    area = models.CharField(max_length=128, blank=True)

    # Daily availability window (simple version)
    available_from = models.TimeField()   # 09:00
    available_to = models.TimeField()     # 15:00

    # Helper is okay with: ["one_time", "weekly", "monthly"]
    frequency_modes = ArrayField(
        models.CharField(max_length=32),
        default=list,
        help_text='Acceptable frequencies: "one_time", "weekly", "monthly"',
    )

    experience_years = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["city", "active"]),
        ]

    def __str__(self):
        return f"HelperProfile({self.user.phone_number})"


class SeekerPreferences(models.Model):
    """
    The seeker's default preference template:
    what they USUALLY want (services, time window, frequency, location).
    Only applies when user.user_type == 'user' (seeker).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="seeker_prefs",
    )

    # Example: ["cooking", "cleaning"]
    required_services = ArrayField(
        models.CharField(max_length=64),
        default=list,
        help_text="List of required service slugs",
    )

    city = models.CharField(max_length=128)
    area = models.CharField(max_length=128, blank=True)

    from_time = models.TimeField()   # e.g. 09:00
    to_time = models.TimeField()     # e.g. 15:00

    # "one_time", "weekly", "monthly"
    frequency = models.CharField(max_length=32)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SeekerPreferences({self.user.phone_number})"
