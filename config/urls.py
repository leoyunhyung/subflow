from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # API
    path("api/v1/accounts/", include("apps.accounts.urls")),
    path("api/v1/vendors/", include("apps.vendors.urls")),
    path("api/v1/plans/", include("apps.plans.urls")),
    path("api/v1/subscriptions/", include("apps.subscriptions.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/settlements/", include("apps.settlements.urls")),
    # Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
