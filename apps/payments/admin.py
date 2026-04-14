from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order_id", "user", "amount", "status", "paid_at")
    list_filter = ("status",)
