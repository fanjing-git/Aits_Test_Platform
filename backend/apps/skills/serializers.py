from typing import Any
import hashlib
import json

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.projects.models import Project
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import Skill, SkillChain, SkillChainConfiguration, SkillChainGovernanceAudit, SkillChainNodeRun, SkillChainRun, SkillChainRunEvent, SkillInstallation, SkillPermissionAudit
from apps.skills.contracts import SkillChainContractError, legacy_skill_ids, validate_skill_chain_definition

class SkillSerializer(serializers.ModelSerializer):
    """Serialize Skill definitions without runtime internals."""
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    class Meta:
        model = Skill
        fields = ('id','project','project_name','name','version','description','category','category_label','triggers','capabilities','tools','knowledge','input_schema','output_schema','runtime_key','timeout_seconds','status','status_label','created_by','created_at','updated_at')
        read_only_fields = ('id','created_by','created_at','updated_at')
    def validate(self, attrs):
        """Enforce global/custom scope and caller project membership."""
        request = self.context['request']; project = attrs.get('project', getattr(self.instance, 'project', None)); category = attrs.get('category', getattr(self.instance, 'category', Skill.Category.CORE))
        if category == Skill.Category.CUSTOM and project is None: raise serializers.ValidationError({'project':'自定义技能必须关联项目。'})
        if category != Skill.Category.CUSTOM and project is not None: raise serializers.ValidationError({'project':'内置技能不能绑定项目。'})
        if project is None and getattr(request.user.profile, 'role', None) != 'admin': raise serializers.ValidationError({'project':'共享技能仅平台管理员可管理。'})
        if project is not None and not (getattr(request.user.profile, 'role', None) == 'admin' or project.memberships.filter(user=request.user).values('role').exists()): raise serializers.ValidationError({'project':'项目不存在或不可访问。'})
        return attrs
    def create(self, validated_data): return Skill.objects.create(created_by=self.context['request'].user, **validated_data)


class SkillPermissionAuditSerializer(serializers.ModelSerializer):
    """Expose safe permission decisions without request values."""

    installation_source = serializers.CharField(source="installation.source_url", read_only=True)
    actor_username = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = SkillPermissionAudit
        fields = ("id", "installation", "installation_source", "permission", "allowed", "reason", "context_keys", "actor", "actor_username", "created_at")
        read_only_fields = fields


class SkillInstallationSerializer(serializers.ModelSerializer):
    """Serialize installation lifecycle, association and truthful readiness separately."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True, allow_null=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)
    installed_by_username = serializers.CharField(source="installed_by.username", read_only=True, allow_null=True)
    permissions = serializers.SerializerMethodField()
    linked_skill_name = serializers.CharField(source="skill.name", read_only=True, allow_null=True)
    linked_skill_version = serializers.CharField(source="skill.version", read_only=True, allow_null=True)
    linked_skill_status = serializers.CharField(source="skill.status", read_only=True, allow_null=True)
    installed = serializers.SerializerMethodField()
    installation_state_label = serializers.SerializerMethodField()
    runtime_ready = serializers.SerializerMethodField()
    runtime_ready_reason = serializers.SerializerMethodField()

    class Meta:
        model = SkillInstallation
        fields = (
            "id", "skill", "linked_skill_name", "linked_skill_version", "linked_skill_status",
            "source_type", "source_url", "version", "manifest", "permissions", "commit_hash",
            "file_hash", "status", "status_label", "installed", "installation_state_label",
            "runtime_ready", "runtime_ready_reason", "error_message", "requested_by",
            "requested_by_username", "approved_by", "approved_by_username", "approved_at",
            "installed_by", "installed_by_username", "installed_at", "rolled_back_at",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_permissions(self, obj):
        """Return only normalized boolean permissions from the stored manifest."""
        value = obj.manifest.get("permissions", {}) if isinstance(obj.manifest, dict) else {}
        return value if isinstance(value, dict) else {}

    def get_installed(self, obj):
        """Distinguish an installed artifact from earlier lifecycle states."""
        return obj.status == SkillInstallation.Status.INSTALLED

    def get_installation_state_label(self, obj):
        """Return the installation state independently of runtime readiness."""
        return "已安装" if obj.status == SkillInstallation.Status.INSTALLED else "未安装"

    def get_runtime_ready(self, obj):
        """Never infer readiness from installation or placeholder echo behavior."""
        return False

    def get_runtime_ready_reason(self, obj):
        """Explain the current controlled-adapter and preflight boundary."""
        return "尚无受控适配器和真实运行环境预检；安装成功不代表运行就绪。"


class SkillChainSerializer(serializers.ModelSerializer):
    """Serialize a complete Skill-chain contract and safe compatibility metadata."""

    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), allow_null=True, required=False)
    project_name = serializers.CharField(source="project.name", read_only=True, allow_null=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    configuration_count = serializers.IntegerField(source="configurations.count", read_only=True)
    can_rollback = serializers.SerializerMethodField()

    class Meta:
        model = SkillChain
        fields = (
            "id", "project", "project_name", "name", "version", "description",
            "schema_version", "definition", "legacy_skill_ids", "status", "status_label",
            "published_at", "can_rollback", "configuration_count", "created_by", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "schema_version", "status", "status_label", "published_at",
            "can_rollback", "configuration_count", "created_by", "created_at", "updated_at",
        )
        validators = []

    def get_can_rollback(self, obj: SkillChain) -> bool:
        """Expose whether this version has an earlier published rollback target."""
        from apps.skills.services import chain_has_rollback_target

        return chain_has_rollback_target(obj)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate scope and canonicalize the full chain contract."""
        request = self.context["request"]
        project = attrs.get("project", getattr(self.instance, "project", None))
        if project is not None and not (
            getattr(request.user.profile, "role", None) == "admin"
            or project.memberships.filter(user=request.user).values("role").exists()
        ):
            raise serializers.ValidationError({"project": "项目不存在或不可访问。"})
        if project is None and getattr(request.user.profile, "role", None) != "admin":
            raise serializers.ValidationError({"project": "共享 Skill 链仅平台管理员可管理。"})
        if SkillChain.objects.filter(project=project, name=attrs.get("name", getattr(self.instance, "name", "")), version=attrs.get("version", getattr(self.instance, "version", "1.0.0"))).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError({"version": "同一范围内的链名称和版本不能重复。"})
        if "definition" in attrs:
            try:
                attrs["definition"] = validate_skill_chain_definition(attrs["definition"])
            except SkillChainContractError as exc:
                raise serializers.ValidationError({"definition": str(exc)}) from exc
        if "legacy_skill_ids" in attrs:
            try:
                attrs["legacy_skill_ids"] = legacy_skill_ids(attrs["legacy_skill_ids"])
            except SkillChainContractError as exc:
                raise serializers.ValidationError({"legacy_skill_ids": str(exc)}) from exc
        if self.instance is not None and attrs.get("version", self.instance.version) != self.instance.version:
            raise serializers.ValidationError({"version": "已创建的蓝图版本编号不可修改；请从此版本派生新的草稿版本。"})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> SkillChain:
        """Persist a chain with the authenticated creator attached."""
        validated_data.setdefault("created_by", self.context["request"].user)
        return SkillChain.objects.create(**validated_data)


class SkillChainNodeRunSerializer(serializers.ModelSerializer):
    """Serialize node state and safe snapshots for the execution workbench."""

    class Meta:
        model = SkillChainNodeRun
        fields = (
            "id", "node_id", "position", "node_type", "status", "definition_snapshot",
            "input_snapshot", "output_snapshot", "attempt", "max_retries", "checkpoint_safe",
            "error_code", "error_message", "started_at", "finished_at",
        )
        read_only_fields = fields


class SkillChainRunEventSerializer(serializers.ModelSerializer):
    """Serialize append-only run lineage events."""

    node_id = serializers.CharField(source="node_key", read_only=True)

    class Meta:
        model = SkillChainRunEvent
        fields = ("id", "sequence", "event_type", "from_status", "to_status", "node_id", "payload", "created_at")
        read_only_fields = fields


class SkillChainRunSerializer(serializers.ModelSerializer):
    """Serialize one parent run with its durable node records."""

    chain_name = serializers.CharField(source="chain.name", read_only=True, allow_null=True)
    chain_version = serializers.CharField(source="chain.version", read_only=True, allow_null=True)
    nodes = SkillChainNodeRunSerializer(many=True, read_only=True)

    class Meta:
        model = SkillChainRun
        fields = (
            "id", "chain", "chain_name", "chain_version", "configuration", "project", "requested_by",
            "idempotency_key", "status", "input_snapshot", "execution_snapshot", "output_snapshot",
            "current_node_id", "checkpoint_node_id", "control_request", "error_code", "error_message",
            "attempt", "task_id", "started_at", "finished_at", "created_at", "updated_at", "nodes",
        )
        read_only_fields = fields


class SkillChainGovernanceAuditSerializer(serializers.ModelSerializer):
    """Serialize safe chain configuration and lifecycle audit events."""

    actor_id = serializers.ReadOnlyField()
    actor_username = serializers.CharField(source="actor.username", read_only=True, allow_null=True)
    actor_display_name = serializers.SerializerMethodField()
    actor_role = serializers.CharField(read_only=True, allow_blank=True)
    actor_scope = serializers.JSONField(read_only=True)
    result = serializers.CharField(read_only=True)
    before_state = serializers.SerializerMethodField()
    after_state = serializers.SerializerMethodField()

    class Meta:
        model = SkillChainGovernanceAudit
        fields = (
            "id", "object_id", "action", "before_state", "after_state", "reason",
            "actor_id", "actor_username", "actor_display_name", "actor_role",
            "actor_scope", "result", "created_at",
        )
        read_only_fields = fields

    def get_actor_display_name(self, obj: SkillChainGovernanceAudit) -> str:
        """Show the captured name or clearly identify a legacy record."""
        if obj.actor_display_name:
            return obj.actor_display_name
        if obj.actor_id and obj.actor is not None:
            return f"{obj.actor.get_username()}（历史操作者，未留存显示名快照）"
        return "历史记录 / 操作者未知"

    @staticmethod
    def _safe_state(value: object) -> object:
        """Redact arbitrary configuration values while retaining useful audit diffs."""
        if not isinstance(value, dict) or "configuration_snapshot" not in value:
            return value
        snapshot = value.get("configuration_snapshot")
        chain = snapshot.get("chain", {}) if isinstance(snapshot, dict) else {}
        overrides = value.get("overrides", {})
        return {
            "chain_id": value.get("chain_id"),
            "layer": value.get("layer"),
            "project_id": value.get("project_id"),
            "feature_key": value.get("feature_key", ""),
            "request_key": value.get("request_key", ""),
            "version_lock": value.get("version_lock", ""),
            "enabled": value.get("enabled"),
            "overrides": {"keys": sorted(overrides) if isinstance(overrides, dict) else []},
            "configuration_snapshot": {
                "snapshot_schema_version": snapshot.get("snapshot_schema_version", "") if isinstance(snapshot, dict) else "",
                "chain": {
                    "id": chain.get("id"),
                    "name": chain.get("name"),
                    "version": chain.get("version"),
                    "definition_sha256": hashlib.sha256(
                        json.dumps(chain.get("definition", {}), ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest() if isinstance(chain, dict) else "",
                },
            },
        }

    def get_before_state(self, obj: SkillChainGovernanceAudit) -> object:
        """Return a redacted before-state summary."""
        return self._safe_state(obj.before_state)

    def get_after_state(self, obj: SkillChainGovernanceAudit) -> object:
        """Return a redacted after-state summary."""
        return self._safe_state(obj.after_state)


class SkillChainConfigurationSerializer(serializers.ModelSerializer):
    """Serialize configuration declarations and rollback availability."""

    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all(), allow_null=True, required=False)
    chain_name = serializers.CharField(source="chain.name", read_only=True)
    layer_label = serializers.CharField(source="get_layer_display", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, allow_null=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True, allow_null=True)
    configuration_snapshot = serializers.JSONField(read_only=True)
    can_rollback = serializers.SerializerMethodField()
    audit_count = serializers.SerializerMethodField()

    class Meta:
        model = SkillChainConfiguration
        fields = (
            "id", "chain", "chain_name", "layer", "layer_label", "project", "project_name",
            "feature_key", "request_key", "version_lock", "overrides", "configuration_snapshot",
            "enabled", "created_by", "created_by_username", "created_at", "updated_at",
            "can_rollback", "audit_count",
        )
        read_only_fields = (
            "id", "chain_name", "layer_label", "project_name", "created_by",
            "created_by_username", "created_at", "updated_at", "can_rollback", "audit_count",
        )
        validators = []

    def get_audit_count(self, obj: SkillChainConfiguration) -> int:
        """Return the retained governance-event count for this configuration."""
        return obj.governance_audits.count()

    def get_can_rollback(self, obj: SkillChainConfiguration) -> bool:
        """Expose whether an earlier audited configuration state exists."""
        return obj.governance_audits.count() > 1

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate layer scope and require manager-level write access."""
        request = self.context["request"]
        chain = attrs.get("chain", getattr(self.instance, "chain", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        layer = attrs.get("layer", getattr(self.instance, "layer", None))
        visible_project = project or getattr(chain, "project", None)
        if visible_project is not None and not (
            is_platform_admin(request.user) or project_role(request.user, visible_project) is not None
        ):
            raise serializers.ValidationError({"project": "项目不存在或不可访问。"})
        if layer == SkillChainConfiguration.Layer.GLOBAL and not is_platform_admin(request.user):
            raise serializers.ValidationError({"layer": "全局默认配置仅平台管理员可管理。"})
        if not is_platform_admin(request.user):
            if visible_project is None or project_role(request.user, visible_project) not in {"owner", "manager"}:
                raise serializers.ValidationError({"project": "只有项目所有者或管理员可以维护项目 Skill 链配置。"})
        if SkillChainConfiguration.objects.filter(
            chain=chain,
            layer=layer,
            project=project,
            feature_key=attrs.get("feature_key", getattr(self.instance, "feature_key", "")),
            request_key=attrs.get("request_key", getattr(self.instance, "request_key", "")),
        ).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError({"scope": "同一链和范围不能重复保存配置。"})
        candidate = SkillChainConfiguration(
            chain=chain,
            project=project,
            layer=layer,
            feature_key=attrs.get("feature_key", getattr(self.instance, "feature_key", "")),
            request_key=attrs.get("request_key", getattr(self.instance, "request_key", "")),
            version_lock=attrs.get("version_lock", getattr(self.instance, "version_lock", "")),
            overrides=attrs.get("overrides", getattr(self.instance, "overrides", {})),
            enabled=attrs.get("enabled", getattr(self.instance, "enabled", True)),
        )
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"scope": str(exc)}) from exc
        return attrs

    def create(self, validated_data: dict[str, Any]) -> SkillChainConfiguration:
        """Persist a layer configuration with the authenticated creator."""
        validated_data.setdefault("created_by", self.context["request"].user)
        return SkillChainConfiguration.objects.create(**validated_data)
