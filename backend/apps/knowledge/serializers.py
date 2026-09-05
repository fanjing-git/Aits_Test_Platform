"""Safe serializers for knowledge collections, documents and QA."""
from rest_framework import serializers
from apps.knowledge.models import Document, Embedding, KnowledgeBase, QAPair
from apps.projects.models import Project

class KnowledgeBaseSerializer(serializers.ModelSerializer):
    """Represent a knowledge collection without internal details."""
    project_name = serializers.CharField(source='project.name', read_only=True)
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    class Meta:
        model = KnowledgeBase
        fields = ('id','project','project_name','name','description','category','category_label','status','status_label','metadata','created_by','created_at','updated_at')
        read_only_fields = ('id','created_by','created_at','updated_at')
    def validate_project(self, value):
        """Require the caller to belong to the selected project."""
        user = self.context['request'].user
        if value is None:
            if getattr(user.profile, 'role', None) == 'admin':
                return value
            raise serializers.ValidationError('项目级知识库必须绑定项目。')
        if not value.memberships.filter(user=user).exists() and getattr(user.profile, 'role', None) != 'admin':
            raise serializers.ValidationError('项目不存在或不可访问。')
        return value
    def create(self, validated_data):
        """Assign the authenticated creator."""
        return KnowledgeBase.objects.create(created_by=self.context['request'].user, **validated_data)

class DocumentSerializer(serializers.ModelSerializer):
    """Accept metadata and uploaded file while never exposing server paths."""
    knowledge_base_name = serializers.CharField(source='knowledge_base.name', read_only=True)
    source_type_label = serializers.CharField(source='get_source_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    review_status_label = serializers.CharField(source='get_review_status_display', read_only=True)
    class Meta:
        model = Document
        fields = ('id','knowledge_base','knowledge_base_name','title','source_type','source_type_label','source_url','content_text','status','status_label','review_status','review_status_label','review_note','reviewed_by','reviewed_at','metadata','created_by','created_at','updated_at','file')
        read_only_fields = ('id','status','review_status','review_note','reviewed_by','reviewed_at','created_by','created_at','updated_at')
        extra_kwargs = {'file': {'write_only': True, 'required': False}}
    file = serializers.FileField(write_only=True, required=False)
    def validate_knowledge_base(self, value):
        """Require project visibility before any document is created."""
        user=self.context['request'].user
        if not (getattr(user.profile,'role',None)=='admin' or value.project_id and value.project.memberships.filter(user=user).exists()): raise serializers.ValidationError('知识库不存在或不可访问。')
        return value
    def create(self, validated_data):
        """Store an uploaded file under a generated safe name."""
        upload=validated_data.pop('file',None)
        if upload:
            from pathlib import Path
            from uuid import uuid4
            from django.conf import settings
            ext=Path(upload.name).suffix.lower()
            if ext not in {'.txt','.md','.markdown','.pdf','.docx'}: raise serializers.ValidationError({'file':'仅支持 TXT、Markdown、PDF 和 DOCX。'})
            root=Path(settings.KNOWLEDGE_DOCUMENT_ROOT); root.mkdir(parents=True, exist_ok=True)
            target=root/(uuid4().hex+ext)
            if upload.size > settings.KNOWLEDGE_DOCUMENT_MAX_BYTES: raise serializers.ValidationError({'file':'文件超过大小限制。'})
            with target.open('wb') as handle:
                for chunk in upload.chunks(): handle.write(chunk)
            validated_data['file_path']=str(target); validated_data['source_type']=Document.SourceType.FILE
        return Document.objects.create(created_by=self.context['request'].user, **validated_data)

class QAPairSerializer(serializers.ModelSerializer):
    """Represent reviewable questions and answers."""
    review_status_label=serializers.CharField(source='get_review_status_display',read_only=True)
    class Meta:
        model=QAPair
        fields=('id','knowledge_base','question','answer','review_status','review_status_label','quality_score','source_document','metadata','created_by','reviewed_by','reviewed_at','created_at','updated_at')
        read_only_fields=('id','review_status','reviewed_by','reviewed_at','created_by','created_at','updated_at')
    def validate_knowledge_base(self,value):
        user=self.context['request'].user
        if not (getattr(user.profile,'role',None)=='admin' or value.project_id and value.project.memberships.filter(user=user).exists()): raise serializers.ValidationError('知识库不存在或不可访问。')
        return value
    def create(self,validated_data): return QAPair.objects.create(created_by=self.context['request'].user,**validated_data)
