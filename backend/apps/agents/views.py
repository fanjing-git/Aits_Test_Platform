"""Version-aware REST endpoints for agent configurations."""

from django.db import IntegrityError, transaction
from django.db.models import F, Max, OuterRef, Subquery
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.agents.models import Agent
from apps.agents.permissions import AgentObjectPermission, can_edit_agents
from apps.agents.serializers import AgentSerializer
from apps.configs.models import ModelConfig, PromptConfig
from apps.projects.models import Project
from apps.projects.permissions import is_platform_admin, project_role


class AgentViewSet(viewsets.ModelViewSet):
    serializer_class = AgentSerializer
    permission_classes = (AgentObjectPermission,)
    queryset = Agent.objects.all()

    @action(detail=False, methods=("get",))
    def options(self, request):
        """Expose non-secret active configuration choices to the workspace UI."""
        models = ModelConfig.objects.filter(is_active=True).values(
            "id", "name", "provider", "model_name"
        )
        prompts = PromptConfig.objects.filter(is_active=True).values(
            "id", "name", "scope", "scene_type", "version"
        )
        return Response({"models": list(models), "prompts": list(prompts)})

    def create(self, request, *args, **kwargs):
        project_id = request.data.get("project_id")
        project = Project.objects.filter(pk=project_id).first() if project_id else None
        if project is not None and not can_edit_agents(request.user, project):
            raise PermissionDenied("仅项目所有者、项目管理员或平台管理员可创建智能体。")
        return super().create(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Agent.objects.select_related(
            "project", "model_config", "prompt_config", "created_by"
        )
        if not is_platform_admin(self.request.user):
            queryset = queryset.filter(
                project__memberships__user=self.request.user
            )
        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if self.request.query_params.get("include_history") != "true":
            latest_version = (
                Agent.objects.filter(project=OuterRef("project"), name=OuterRef("name"))
                .values("project", "name")
                .annotate(latest=Max("version"))
                .values("latest")[:1]
            )
            queryset = queryset.annotate(_latest=Subquery(latest_version)).filter(
                version=F("_latest")
            )
        return queryset.distinct()

    def perform_create(self, serializer):
        project = serializer.validated_data["project"]
        if not can_edit_agents(self.request.user, project):
            raise PermissionDenied("仅项目所有者、项目管理员或平台管理员可创建智能体。")
        try:
            serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"name": "该项目中已存在同名智能体。"}) from exc

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        current = self.get_object()
        if not can_edit_agents(request.user, current.project):
            raise PermissionDenied("当前项目角色不能编辑智能体。")
        serializer = self.get_serializer(current, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            versions = Agent.objects.select_for_update().filter(
                project=current.project, name=current.name
            )
            latest = versions.order_by("-version").first()
            if latest.pk != current.pk:
                raise ValidationError("只能从最新版本继续编辑。")
            values = {
                "project": current.project,
                "name": current.name,
                "description": current.description,
                "agent_type": current.agent_type,
                "model_config": current.model_config,
                "prompt_config": current.prompt_config,
                "knowledge_base_ids": list(current.knowledge_base_ids),
                "skill_ids": list(current.skill_ids),
                "parameters": dict(current.parameters),
                "status": current.status,
            }
            values.update(serializer.validated_data)
            values["project"] = current.project
            values["name"] = current.name
            new_version = Agent(
                **values,
                version=latest.version + 1,
                created_by=request.user,
            )
            new_version.full_clean()
            new_version.save()
        return Response(self.get_serializer(new_version).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        current = self.get_object()
        if not (
            is_platform_admin(request.user)
            or project_role(request.user, current.project) == "owner"
        ):
            raise PermissionDenied("仅项目所有者或平台管理员可删除智能体。")
        Agent.objects.filter(project=current.project, name=current.name).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=("get",))
    def history(self, request, pk=None):
        current = self.get_object()
        history = Agent.objects.filter(
            project=current.project, name=current.name
        ).select_related("project", "model_config", "prompt_config", "created_by")
        return Response(self.get_serializer(history, many=True).data)

    @action(detail=True, methods=("post",))
    def rollback(self, request, pk=None):
        current = self.get_object()
        if not can_edit_agents(request.user, current.project):
            raise PermissionDenied("当前项目角色不能回滚智能体。")
        try:
            target_version = int(request.data.get("version"))
        except (TypeError, ValueError):
            raise ValidationError({"version": "必须提供有效的目标版本。"})
        with transaction.atomic():
            versions = Agent.objects.select_for_update().filter(
                project=current.project, name=current.name
            )
            latest = versions.order_by("-version").first()
            target = versions.filter(version=target_version).first()
            if target is None:
                raise ValidationError({"version": "目标版本不存在。"})
            restored = Agent(
                project=target.project,
                name=target.name,
                description=target.description,
                agent_type=target.agent_type,
                model_config=target.model_config,
                prompt_config=target.prompt_config,
                knowledge_base_ids=list(target.knowledge_base_ids),
                skill_ids=list(target.skill_ids),
                parameters=dict(target.parameters),
                version=latest.version + 1,
                status=target.status,
                created_by=request.user,
            )
            restored.full_clean()
            restored.save()
        return Response(self.get_serializer(restored).data, status=status.HTTP_201_CREATED)
