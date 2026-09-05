from rest_framework import serializers
from apps.skills.models import Skill

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
