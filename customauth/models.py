# in your Django app’s models.py
import uuid
from django.db import models
from django.contrib.auth.hashers import make_password, check_password  # or use Django’s auth framework

class User(models.Model):
    class UserType(models.TextChoices):
        ADMIN = "admin", "Admin"
        USER = "user", "User"
        HELPER = "helper", "Helper"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True)
    password = models.CharField(max_length=255)  # store hashed password, not plain text
    user_type = models.CharField(
        max_length=10,
        choices=UserType.choices,
        default=UserType.USER,
    )

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        self.save()

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

class UserSession(models.Model):
    """
    Per-user session record.

    - session_id: primary key (UUID)
    - version_id: random UUID used inside the token
    - user: FK to User
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # session id
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    version_id = models.UUIDField(default=uuid.uuid4, editable=False)  # random per session version

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def rotate_version(self):
        """
        Invalidate all existing tokens for this session by changing version_id.
        """
        self.version_id = uuid.uuid4()
        self.save(update_fields=["version_id", "updated_at"])

    def __str__(self):
        return f"Session({self.id}) for {self.user.phone_number}"