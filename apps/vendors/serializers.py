from rest_framework import serializers

from .models import Vendor


class VendorSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Vendor
        fields = (
            "id",
            "username",
            "company_name",
            "business_number",
            "status",
            "commission_rate",
            "created_at",
        )
        read_only_fields = ("id", "status", "commission_rate", "created_at")


class VendorCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ("id", "company_name", "business_number", "status")
        read_only_fields = ("id", "status")

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class VendorApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ("status", "commission_rate")

    def validate_status(self, value):
        if value not in ("approved", "rejected"):
            raise serializers.ValidationError("approved 또는 rejected만 가능합니다.")
        return value
