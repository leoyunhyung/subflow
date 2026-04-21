from django.apps import AppConfig


class ChurnPredictionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.churn_prediction"
    verbose_name = "구독 이탈 예측"
