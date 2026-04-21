from rest_framework.routers import DefaultRouter

from apps.churn_prediction.views import (
    ChurnPredictionRunViewSet,
    ChurnPredictionViewSet,
)

router = DefaultRouter()
router.register(r"predictions", ChurnPredictionViewSet, basename="churn-prediction")
router.register(r"runs", ChurnPredictionRunViewSet, basename="churn-run")

urlpatterns = router.urls
