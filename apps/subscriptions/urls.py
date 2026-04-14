from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.SubscriptionListCreateView.as_view(), name="list-create"),
    path("<int:pk>/", views.SubscriptionDetailView.as_view(), name="detail"),
    path("<int:pk>/cancel/", views.SubscriptionCancelView.as_view(), name="cancel"),
]
