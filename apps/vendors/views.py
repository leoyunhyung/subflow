from rest_framework import generics, permissions

from apps.common.permissions import IsAdmin, IsVendor

from .models import Vendor
from .serializers import VendorApprovalSerializer, VendorCreateSerializer, VendorSerializer


class VendorListView(generics.ListAPIView):
    """벤더 목록 (인증된 사용자)"""

    queryset = Vendor.objects.select_related("user").all()
    serializer_class = VendorSerializer


class VendorRegisterView(generics.CreateAPIView):
    """벤더 등록 신청 (vendor role 유저만)"""

    serializer_class = VendorCreateSerializer
    permission_classes = (permissions.IsAuthenticated, IsVendor)


class VendorDetailView(generics.RetrieveAPIView):
    queryset = Vendor.objects.select_related("user").all()
    serializer_class = VendorSerializer


class VendorApprovalView(generics.UpdateAPIView):
    """벤더 승인/거절 (admin만)"""

    queryset = Vendor.objects.all()
    serializer_class = VendorApprovalSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdmin)
