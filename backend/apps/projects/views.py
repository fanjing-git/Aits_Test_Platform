"""Project CRUD and member-management REST endpoints."""

from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.projects.models import Project, ProjectMember
from apps.projects.permissions import (
    ProjectObjectPermission,
    can_manage_members,
    is_platform_admin,
)
from apps.projects.serializers import (
    ProjectMemberSerializer,
    ProjectSerializer,
    ProjectUserSerializer,
)


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = (IsAuthenticated, ProjectObjectPermission)

    def get_queryset(self):
        queryset = Project.objects.select_related("created_by").prefetch_related(
            "memberships__user"
        ).annotate(member_count=Count("memberships", distinct=True))
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(memberships__user=self.request.user)
        return queryset.distinct().order_by("name")

    @action(detail=True, methods=("get", "post"))
    def members(self, request: Request, pk: str | None = None) -> Response:
        project = self.get_object()
        if request.method == "GET":
            members = project.memberships.select_related("user").order_by("user__username")
            return Response(ProjectMemberSerializer(members, many=True).data)
        if not can_manage_members(request.user, project):
            return Response(
                {"detail": "You do not have permission to manage project members."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ProjectMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if ProjectMember.objects.filter(
            project=project, user=serializer.validated_data["user"]
        ).exists():
            return Response(
                {"user_id": ["该用户已经是项目成员。"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        member = serializer.save(project=project)
        return Response(
            ProjectMemberSerializer(member).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=("get",), url_path="member-candidates")
    def member_candidates(self, request: Request, pk: str | None = None) -> Response:
        """Return safe identities that a project manager may add."""
        project = self.get_object()
        if not can_manage_members(request.user, project):
            return Response(
                {"detail": "You do not have permission to manage project members."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user_model = ProjectMember._meta.get_field("user").remote_field.model
        existing_user_ids = project.memberships.values_list("user_id", flat=True)
        candidates = (
            user_model.objects.filter(is_active=True)
            .exclude(pk__in=existing_user_ids)
            .order_by("username")[:100]
        )
        return Response(ProjectUserSerializer(candidates, many=True).data)

    @action(
        detail=True,
        methods=("patch", "delete"),
        url_path=r"members/(?P<member_id>[^/.]+)",
    )
    def member_detail(
        self,
        request: Request,
        pk: str | None = None,
        member_id: str | None = None,
    ) -> Response:
        project = self.get_object()
        if not can_manage_members(request.user, project):
            return Response(
                {"detail": "You do not have permission to manage project members."},
                status=status.HTTP_403_FORBIDDEN,
            )
        member = project.memberships.filter(pk=member_id).select_related("user").first()
        if member is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if member.role == ProjectMember.Role.OWNER:
            return Response(
                {"detail": "项目所有者不能通过成员接口修改或移除。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.method == "DELETE":
            member.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = ProjectMemberSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
