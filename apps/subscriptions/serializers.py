from django.utils import timezone
from dateutil.relativedelta import relativedelta
from rest_framework import serializers

from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "id",
            "user",
            "plan",
            "plan_name",
            "status",
            "started_at",
            "expires_at",
            "cancelled_at",
        )
        read_only_fields = ("id", "user", "status", "started_at", "expires_at", "cancelled_at")

    def create(self, validated_data):
        plan = validated_data["plan"]
        now = timezone.now()
        if plan.billing_cycle == "yearly":
            expires_at = now + relativedelta(years=1)
        else:
            expires_at = now + relativedelta(months=1)

        validated_data["user"] = self.context["request"].user
        validated_data["expires_at"] = expires_at
        return super().create(validated_data)


class SubscriptionCancelSerializer(serializers.Serializer):
    def update(self, instance, validated_data):
        instance.status = "cancelled"
        instance.cancelled_at = timezone.now()
        instance.save(update_fields=["status", "cancelled_at"])
        return instance
