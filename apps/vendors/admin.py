from django.contrib import admin

from .models import Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "status", "commission_rate", "created_at")
    list_filter = ("status",)
    search_fields = ("company_name", "business_number")
