from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "관리자"
        VENDOR = "vendor", "벤더"
        USER = "user", "일반 유저"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.USER,
        verbose_name="역할",
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name="전화번호")

    class Meta:
        db_table = "users"
        verbose_name = "사용자"
        verbose_name_plural = "사용자"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN

    @property
    def is_vendor(self):
        return self.role == self.Role.VENDOR
