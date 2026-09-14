"""REST serializers for versioned agent configurations."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.agents.models import Agent, AgentExecution
from apps.configs.models import ModelConfig, PromptConfig
from apps.projects.models import Project


class AgentCreatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ("id", "username", "email")


class AgentSerializer(serializers.ModelSerializer):
    project_id = serializers.PrimaryKeyRelatedField(
        source="project", queryset=Project.objects.all()
    )
    model_config_id = serializers.PrimaryKeyRelatedField(
        source="model_config", queryset=ModelConfig.objects.filter(is_active=True)
    )
    prompt_config_id = serializers.PrimaryKeyRelatedField(
        source="prompt_config",
        queryset=PromptConfig.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    created_by = AgentCreatorSerializer(read_only=True)
    agent_type_label = serializers.CharField(
        source="get_agent_type_display", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Agent
        fields = (
            "id",
            "project_id",
            "name",
            "description",
            "agent_type",
            "agent_type_label",
            "model_config_id",
            "prompt_config_id",
            "knowledge_base_ids",
            "skill_ids",
            "parameters",
            "version",
            "status",
            "status_label",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("version", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        instance = self.instance
        if instance:
            if "project" in attrs and attrs["project"] != instance.project:
                raise serializers.ValidationError(
                    {"project_id": "不能把智能体版本移动到其他项目。"}
                )
            if "name" in attrs and attrs["name"] != instance.name:
                raise serializers.ValidationError(
                    {"name": "版本更新不能修改智能体名称。"}
                )
        else:
            project = attrs.get("project")
            name = attrs.get("name")
            if project and name and Agent.objects.filter(project=project, name=name).exists():
                raise serializers.ValidationError(
                    {"name": "该项目中已存在同名智能体。"}
                )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        agent = Agent(**validated_data)
        agent.full_clean()
        agent.save()
        return agent


class AgentExecutionRequestSerializer(serializers.Serializer):
    """Validate the user-controlled input for one agent execution."""

    input_text = serializers.CharField(max_length=20000, trim_whitespace=True)
    interrupt_signal = serializers.ChoiceField(
        choices=("", "pause", "cancel"), required=False, allow_blank=True, default=""
    )


class AgentExecutionSerializer(serializers.ModelSerializer):
    """Expose execution state without the original prompt or credentials."""

    agent_id = serializers.UUIDField(read_only=True)
    project_id = serializers.UUIDField(read_only=True)
    requested_by_id = serializers.IntegerField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AgentExecution
        fields = (
            "id", "agent_id", "project_id", "requested_by_id", "agent_name",
            "agent_version", "status", "status_label", "phase", "interrupt_signal",
            "model_route", "trace", "result", "error_code", "error_message",
            "retryable", "task_id", "started_at", "finished_at", "created_at", "updated_at",
        )
        read_only_fields = fields
