from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField

from customauth.models import User


class Message(models.Model):
    """
    Chat message between two users.
    Attachments stored as list of URL paths (strings).
    Physical files live under baaisahab/uploads/messageattachments/.
    Filenames: <message_id>-<ordinal>.<ext>.
    """

    id = models.BigAutoField(primary_key=True)  # messageId
    from_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_messages"
    )
    to_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="received_messages"
    )

    content = models.TextField(blank=True)  # messageContents

    # List of URL strings: ["/uploads/messageattachments/123-1.jpg", ...]
    attachments = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="List of attachment URL paths for this message",
    )

    is_seen = models.BooleanField(default=False)
    time_sent = models.DateTimeField(auto_now_add=True)
    time_seen = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["time_sent"]

    def mark_seen(self):
        if not self.is_seen:
            self.is_seen = True
            self.time_seen = timezone.now()
            self.save(update_fields=["is_seen", "time_seen"])

    def soft_delete(self):
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=["is_deleted", "deleted_at"])
