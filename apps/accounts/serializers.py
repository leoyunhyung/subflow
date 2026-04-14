from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "role", "phone", "date_joined")
        read_only_fields = ("id", "role", "date_joined")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("username", "email", "password", "role", "phone")

    def validate_role(self, value):
        if value == "admin":
            raise serializers.ValidationError("admin 역할은 직접 가입할 수 없습니다.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
