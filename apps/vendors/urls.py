from django.urls import path

from . import views

app_name = "vendors"

urlpatterns = [
    path("", views.VendorListView.as_view(), name="list"),
    path("register/", views.VendorRegisterView.as_view(), name="register"),
    path("<int:pk>/", views.VendorDetailView.as_view(), name="detail"),
    path("<int:pk>/approve/", views.VendorApprovalView.as_view(), name="approve"),
]
