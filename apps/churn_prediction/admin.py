from django.contrib import admin

from apps.churn_prediction.models import (
    ChurnFeatureSnapshot,
    ChurnPrediction,
    ChurnPredictionRun,
)


@admin.register(ChurnPrediction)
class ChurnPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "subscription",
        "prediction_date",
        "risk_score",
        "risk_level",
        "llm_model",
        "created_at",
    )
    list_filter = ("risk_level", "prediction_date", "llm_provider")
    search_fields = ("subscription__user__username",)
    readonly_fields = tuple(
        f.name for f in ChurnPrediction._meta.fields
    )


@admin.register(ChurnFeatureSnapshot)
class ChurnFeatureSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "subscription", "feature_version", "created_at")
    readonly_fields = tuple(f.name for f in ChurnFeatureSnapshot._meta.fields)


@admin.register(ChurnPredictionRun)
class ChurnPredictionRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "prediction_date",
        "status",
        "trigger_type",
        "expected_count",
        "actual_count",
        "skipped_count",
        "failed_count",
        "is_verified",
        "processed_seconds",
        "estimated_cost_usd",
        "created_at",
    )
    list_filter = ("status", "trigger_type", "prediction_date")
    readonly_fields = tuple(f.name for f in ChurnPredictionRun._meta.fields)
