from django.urls import path

from . import views

app_name = "settlements"

urlpatterns = [
    path("", views.SettlementListView.as_view(), name="list"),
    path("generate/", views.SettlementGenerateView.as_view(), name="generate"),
    path("<int:pk>/complete/", views.SettlementCompleteView.as_view(), name="complete"),
    path("history/", views.SettlementHistoryListView.as_view(), name="history"),
    path("rates/", views.SettlementRateListCreateView.as_view(), name="rates"),
]
