from rest_framework import serializers

from .models import Settlement, SettlementHistory, SettlementRate, UserSettlement


class SettlementRateSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)

    class Meta:
        model = SettlementRate
        fields = (
            "id", "vendor", "vendor_name", "commission_rate",
            "effective_date", "memo", "created_at",
        )
        read_only_fields = ("id", "created_at")


class UserSettlementSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = UserSettlement
        fields = (
            "id", "username", "payment", "amount",
            "commission", "payout", "created_at",
        )


class SettlementSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)
    applied_rate = serializers.DecimalField(
        source="settlement_rate.commission_rate",
        max_digits=5, decimal_places=2,
        read_only=True, default=None,
    )
    user_settlements = UserSettlementSerializer(many=True, read_only=True)

    class Meta:
        model = Settlement
        fields = (
            "id", "vendor", "vendor_name", "applied_rate",
            "period_start", "period_end",
            "total_sales", "commission", "payout_amount",
            "status", "created_at", "settled_at",
            "user_settlements",
        )
        read_only_fields = (
            "id", "total_sales", "commission", "payout_amount", "created_at",
        )


class SettlementHistorySerializer(serializers.ModelSerializer):
    executed_by_name = serializers.CharField(
        source="executed_by.username", read_only=True, default="",
    )
    integrity_message = serializers.CharField(read_only=True)

    class Meta:
        model = SettlementHistory
        fields = (
            "id", "period_start", "period_end", "status",
            "executed_by_name",
            "expected_settlements", "actual_settlements",
            "expected_user_settlements", "actual_user_settlements",
            "total_commission", "is_verified", "integrity_message",
            "processed_seconds", "error_message", "created_at",
        )
