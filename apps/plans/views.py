from rest_framework import permissions, viewsets

from apps.common.permissions import IsVendor, IsVendorOwner

from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    queryset = Plan.objects.select_related("vendor").filter(is_active=True)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        # create, update, delete → 벤더만
        return [permissions.IsAuthenticated(), IsVendor(), IsVendorOwner()]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role == "vendor" and self.action not in ("list", "retrieve"):
            return qs.filter(vendor__user=self.request.user)
        return qs
