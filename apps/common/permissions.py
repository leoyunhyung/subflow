from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "admin"


class IsVendor(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "vendor"


class IsUser(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "user"


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user.is_authenticated
        return request.user.is_authenticated and request.user.role == "admin"


class IsVendorOwner(BasePermission):
    """벤더 본인 리소스만 접근 가능"""

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True
        if hasattr(obj, "vendor"):
            return obj.vendor.user == request.user
        if hasattr(obj, "user"):
            return obj.user == request.user
        return False
