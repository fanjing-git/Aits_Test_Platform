"""Authentication API views."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.serializers import (
    AccountTokenObtainPairSerializer,
    RegistrationSerializer,
    UserSerializer,
    UserManagementSerializer,
)
from apps.users.permissions import IsAdminRole

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Create a platform account with a default viewer profile."""

    serializer_class = RegistrationSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return public user details after successful registration."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Authenticate an account by username or email and return JWT tokens."""

    permission_classes = (permissions.AllowAny,)

    def post(self, request: Request) -> Response:
        """Validate credentials and issue an access/refresh token pair."""
        serializer = AccountTokenObtainPairSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        update_last_login(None, serializer.user)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """Return details for the user represented by the access token."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request: Request) -> Response:
        """Serialize the authenticated user without sensitive fields."""
        return Response(UserSerializer(request.user).data)


class UserManagementListView(generics.ListAPIView):
    """List platform accounts for administrators without sensitive fields."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)
    serializer_class = UserManagementSerializer
    queryset = User.objects.select_related("profile").order_by("username")


class UserManagementDetailView(generics.RetrieveUpdateAPIView):
    """Allow administrators to update role and active state only."""

    permission_classes = (permissions.IsAuthenticated, IsAdminRole)
    serializer_class = UserManagementSerializer
    queryset = User.objects.select_related("profile").all()
    http_method_names = ("get", "patch", "head", "options")
