from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsUser

from .models import Subscription
from .serializers import SubscriptionCancelSerializer, SubscriptionSerializer


class SubscriptionListCreateView(generics.ListCreateAPIView):
    serializer_class = SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated, IsUser)

    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user).select_related("plan")


class SubscriptionDetailView(generics.RetrieveAPIView):
    serializer_class = SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if self.request.user.role == "admin":
            return Subscription.objects.all()
        return Subscription.objects.filter(user=self.request.user)


class SubscriptionCancelView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        try:
            sub = Subscription.objects.get(pk=pk, user=request.user, status="active")
        except Subscription.DoesNotExist:
            return Response({"detail": "활성 구독을 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SubscriptionCancelSerializer()
        serializer.update(sub, {})
        return Response(SubscriptionSerializer(sub).data)
