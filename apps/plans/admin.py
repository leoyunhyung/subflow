from django.contrib import admin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "tier", "billing_cycle", "price", "is_active")
    list_filter = ("tier", "billing_cycle", "is_active")
