from rest_framework import serializers

from apps.churn_prediction.models import (
    ChurnFeatureSnapshot,
    ChurnPrediction,
    ChurnPredictionRun,
)


class ChurnFeatureSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChurnFeatureSnapshot
        fields = ("id", "feature_data", "feature_version", "created_at")


class ChurnPredictionSerializer(serializers.ModelSerializer):
    feature_snapshot = ChurnFeatureSnapshotSerializer(read_only=True)
    risk_level_display = serializers.CharField(
        source="get_risk_level_display", read_only=True
    )

    class Meta:
        model = ChurnPrediction
        fields = (
            "id",
            "subscription",
            "prediction_date",
            "risk_score",
            "risk_level",
            "risk_level_display",
            "reasoning",
            "recommended_actions",
            "llm_provider",
            "llm_model",
            "prompt_version",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "feature_snapshot",
            "created_at",
        )
        read_only_fields = fields


class ChurnPredictionRunSerializer(serializers.ModelSerializer):
    integrity_message = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ChurnPredictionRun
        fields = (
            "id",
            "prediction_date",
            "status",
            "status_display",
            "trigger_type",
            "executed_by",
            "expected_count",
            "actual_count",
            "skipped_count",
            "failed_count",
            "is_verified",
            "integrity_message",
            "processed_seconds",
            "total_input_tokens",
            "total_output_tokens",
            "estimated_cost_usd",
            "error_message",
            "created_at",
        )
        read_only_fields = fields
