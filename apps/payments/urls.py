from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.PaymentListView.as_view(), name="list"),
    path("create/", views.PaymentCreateView.as_view(), name="create"),
    path("confirm/", views.PaymentConfirmView.as_view(), name="confirm"),
    path("webhook/", views.PaymentWebhookView.as_view(), name="webhook"),
    path("<int:pk>/cancel/", views.PaymentCancelView.as_view(), name="cancel"),
]
