"""REST serializers for projects and project membership."""

from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.projects.models import Project, ProjectMember

User = get_user_model()


class ProjectUserSerializer(serializers.ModelSerializer):
    """Expose the minimum user identity needed by project collaboration UI."""

    class Meta:
        model = User
        fields = ("id", "username", "email")
        read_only_fields = fields


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = ProjectUserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.filter(is_active=True),
        write_only=True,
    )
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = ProjectMember
        fields = ("id", "user", "user_id", "role", "role_label", "joined_at")
        read_only_fields = ("id", "user", "role_label", "joined_at")

    def validate_role(self, value: str) -> str:
        if value == ProjectMember.Role.OWNER:
            raise serializers.ValidationError("所有者角色不能通过成员接口授予。")
        return value


class ProjectSerializer(serializers.ModelSerializer):
    created_by = ProjectUserSerializer(read_only=True)
    member_count = serializers.SerializerMethodField()
    current_role = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "created_by",
            "status",
            "settings",
            "member_count",
            "current_role",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "created_by",
            "member_count",
            "current_role",
            "created_at",
            "updated_at",
        )

    def get_current_role(self, obj: Project) -> str | None:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        if getattr(request.user, "profile", None) and request.user.profile.role == "admin":
            return "platform_admin"
        membership = next(
            (
                item
                for item in obj.memberships.all()
                if item.user_id == request.user.pk
            ),
            None,
        )
        return membership.role if membership else None

    def get_member_count(self, obj: Project) -> int:
        annotated_count = getattr(obj, "member_count", None)
        return annotated_count if annotated_count is not None else obj.memberships.count()

    @transaction.atomic
    def create(self, validated_data: dict[str, Any]) -> Project:
        project = Project.objects.create(
            created_by=self.context["request"].user,
            **validated_data,
        )
        ProjectMember.objects.create(
            project=project,
            user=project.created_by,
            role=ProjectMember.Role.OWNER,
        )
        return project
