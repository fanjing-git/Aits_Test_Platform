"""Safe environment API input and metadata representations."""
from typing import Any
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from apps.environments.models import Environment
from apps.environments.permissions import can_configure_environment
from apps.environments.services import save_environment
from apps.projects.models import Project
from apps.projects.permissions import is_platform_admin


class EnvironmentSerializer(serializers.ModelSerializer):
    """Accept secret objects only on writes, retaining omitted values."""
    project_id = serializers.UUIDField()
    project_name = serializers.CharField(source="project.name", read_only=True)
    name_label = serializers.CharField(source="get_name_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    health_status_label = serializers.CharField(source="get_health_status_display", read_only=True)
    database_config = serializers.JSONField(write_only=True, required=False)
    auth_config = serializers.JSONField(write_only=True, required=False)
    variables = serializers.JSONField(write_only=True, required=False)
    has_database_config = serializers.SerializerMethodField()
    has_auth_config = serializers.SerializerMethodField()
    has_variables = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta:
        """Exclude ciphertext and prohibit client-assigned health outcomes."""
        model = Environment
        fields = ("id", "project_id", "project_name", "name", "name_label", "base_url", "description", "status", "status_label", "health_check_url", "health_status", "health_status_label", "database_config", "auth_config", "variables", "has_database_config", "has_auth_config", "has_variables", "can_manage", "health_checked_at", "health_message", "health_latency_ms", "created_at", "updated_at")
        read_only_fields = ("id", "health_status", "health_checked_at", "health_message", "health_latency_ms", "created_at", "updated_at")
        validators = []

    def get_has_database_config(self, obj: Environment) -> bool:
        """Report presence without revealing configuration values."""
        return bool(obj.database_config)

    def get_has_auth_config(self, obj: Environment) -> bool:
        """Report whether authentication has been configured."""
        return bool(obj.auth_config)

    def get_has_variables(self, obj: Environment) -> bool:
        """Report whether encrypted variables have been configured."""
        return bool(obj.variables)

    def get_can_manage(self, obj: Environment) -> bool:
        """Supply the frontend with the effective configuration permission."""
        return can_configure_environment(self.context["request"].user, obj.project)

    def validate_project_id(self, value: Any) -> Any:
        """Check visible project and write authorization before uniqueness."""
        projects = Project.objects.all()
        user = self.context["request"].user
        if not is_platform_admin(user):
            projects = projects.filter(memberships__user=user)
        project = projects.filter(pk=value).first()
        if project is None:
            raise NotFound("项目不存在或不可访问。")
        if self.instance and project.pk != self.instance.project_id:
            raise serializers.ValidationError("环境不能移动到其他项目。")
        if not can_configure_environment(user, project):
            raise PermissionDenied("当前角色无权配置此项目环境。")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require configuration objects and reject fabricated health status."""
        if any(field in self.initial_data for field in ("health_status", "health_checked_at", "health_message", "health_latency_ms")):
            raise serializers.ValidationError({"health_status": "健康状态只能由健康检查更新。"})
        for name in ("database_config", "auth_config", "variables"):
            if name in attrs and not isinstance(attrs[name], dict):
                raise serializers.ValidationError({name: "配置必须是 JSON 对象；提交空对象可清空。"})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Environment:
        """Persist a validated new environment."""
        return save_environment(validated_data)

    def update(self, instance: Environment, validated_data: dict[str, Any]) -> Environment:
        """Retain omitted secrets while atomically applying the update."""
        return save_environment(validated_data, instance)
