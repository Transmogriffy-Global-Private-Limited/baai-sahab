# in your Django app’s models.py
import uuid
from django.db import models
from django.contrib.auth.hashers import make_password, check_password  # or use Django’s auth framework

class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True)
    password = models.CharField(max_length=255)  # store hashed password, not plain text

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        self.save()

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
