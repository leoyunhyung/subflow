from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            "id",
            "order_id",
            "user",
            "subscription",
            "amount",
            "status",
            "toss_payment_key",
            "paid_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "order_id",
            "user",
            "status",
            "toss_payment_key",
            "paid_at",
            "created_at",
        )


class PaymentConfirmSerializer(serializers.Serializer):
    payment_key = serializers.CharField()
    order_id = serializers.UUIDField()
    amount = serializers.IntegerField()
