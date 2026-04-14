from rest_framework import serializers

from .models import Plan


class PlanSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)

    class Meta:
        model = Plan
        fields = (
            "id",
            "vendor",
            "vendor_name",
            "name",
            "tier",
            "billing_cycle",
            "price",
            "description",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "vendor", "created_at")

    def create(self, validated_data):
        validated_data["vendor"] = self.context["request"].user.vendor_profile
        return super().create(validated_data)
