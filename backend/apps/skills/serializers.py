from rest_framework import serializers
from apps.skills.models import Skill, SkillInstallation, SkillPermissionAudit

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
    """Serialize installation lifecycle data for the governance workbench."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True, allow_null=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True, allow_null=True)
    installed_by_username = serializers.CharField(source="installed_by.username", read_only=True, allow_null=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = SkillInstallation
        fields = ("id", "skill", "source_type", "source_url", "version", "manifest", "permissions", "commit_hash", "file_hash", "status", "status_label", "error_message", "requested_by", "requested_by_username", "approved_by", "approved_by_username", "approved_at", "installed_by", "installed_by_username", "installed_at", "rolled_back_at", "created_at", "updated_at")
        read_only_fields = fields

    def get_permissions(self, obj):
        """Return only normalized boolean permissions from the stored manifest."""
        value = obj.manifest.get("permissions", {}) if isinstance(obj.manifest, dict) else {}
        return value if isinstance(value, dict) else {}
