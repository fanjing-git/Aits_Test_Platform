"""REST API for knowledge collections, parsing, indexing, search and review."""
from pathlib import Path
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from apps.knowledge.models import Document, KnowledgeBase, QAPair
from apps.knowledge.permissions import KnowledgePermission, can_manage
from apps.projects.permissions import is_platform_admin
from apps.knowledge.serializers import KnowledgeBaseSerializer, DocumentSerializer, QAPairSerializer
from apps.knowledge.loader import load_and_chunk, DocumentLoadError
from apps.knowledge.retrieval import retrieve, vectorize_document
from apps.knowledge.review import review_asset

class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    """Manage visible knowledge collections."""
    serializer_class=KnowledgeBaseSerializer; permission_classes=(KnowledgePermission,)
    def get_queryset(self):
        qs=KnowledgeBase.objects.select_related('project','created_by')
        if not is_platform_admin(self.request.user): qs=qs.filter(project__memberships__user=self.request.user)
        return qs.distinct()
    def perform_update(self, serializer):
        if not can_manage(self.request.user,self.get_object()): self.permission_denied(self.request)
        serializer.save()
    def perform_destroy(self, instance):
        if not can_manage(self.request.user,instance): self.permission_denied(self.request)
        instance.delete()

class DocumentViewSet(viewsets.ModelViewSet):
    """Manage documents and trigger safe local parsing/indexing."""
    serializer_class=DocumentSerializer; permission_classes=(KnowledgePermission,); parser_classes=(JSONParser,MultiPartParser,FormParser)
    def get_queryset(self):
        qs=Document.objects.select_related('knowledge_base','created_by','reviewed_by')
        if not is_platform_admin(self.request.user): qs=qs.filter(knowledge_base__project__memberships__user=self.request.user)
        base=self.request.query_params.get('knowledge_base')
        return qs.filter(knowledge_base_id=base).distinct() if base else qs.distinct()
    @action(detail=True,methods=('post',))
    def parse(self,request,pk=None):
        doc=self.get_object()
        if not can_manage(request.user,doc.knowledge_base): return Response({'detail':'无权解析此文档。'},status=403)
        try: load_and_chunk(doc)
        except DocumentLoadError as exc: raise ValidationError({'detail':str(exc)})
        return Response(self.get_serializer(doc).data)
    @action(detail=True,methods=('post',))
    def index(self,request,pk=None):
        doc=self.get_object()
        if not can_manage(request.user,doc.knowledge_base): return Response({'detail':'无权向量化此文档。'},status=403)
        try: vectorize_document(doc)
        except ValueError as exc: raise ValidationError({'detail':str(exc)})
        return Response(self.get_serializer(doc).data)
    @action(detail=True,methods=('post',))
    def review(self,request,pk=None):
        doc=self.get_object()
        result=review_asset(doc,request.user,request.data.get('decision',''),request.data.get('note',''))
        return Response(self.get_serializer(result).data)

class QAPairViewSet(viewsets.ModelViewSet):
    """Manage reviewable question and answer pairs."""
    serializer_class=QAPairSerializer; permission_classes=(KnowledgePermission,)
    def get_queryset(self):
        qs=QAPair.objects.select_related('knowledge_base','source_document','created_by','reviewed_by')
        if not is_platform_admin(self.request.user): qs=qs.filter(knowledge_base__project__memberships__user=self.request.user)
        base=self.request.query_params.get('knowledge_base')
        return qs.filter(knowledge_base_id=base).distinct() if base else qs.distinct()
    @action(detail=True,methods=('post',))
    def review(self,request,pk=None):
        result=review_asset(self.get_object(),request.user,request.data.get('decision',''),request.data.get('note',''))
        return Response(self.get_serializer(result).data)

class KnowledgeSearchViewSet(viewsets.ViewSet):
    """Search approved indexed knowledge within visible project bases."""
    permission_classes=(KnowledgePermission,)
    def create(self,request):
        query=request.data.get('query',''); ids=request.data.get('knowledge_base_ids')
        if ids is None:
            ids=list(KnowledgeBase.objects.values_list('id',flat=True)) if is_platform_admin(request.user) else list(KnowledgeBase.objects.filter(project__memberships__user=request.user).values_list('id',flat=True))
        else:
            if not isinstance(ids, (list, tuple)):
                raise ValidationError({'knowledge_base_ids':'必须是知识库ID数组。'})
            visible=set(KnowledgeBase.objects.values_list('id',flat=True)) if is_platform_admin(request.user) else set(KnowledgeBase.objects.filter(project__memberships__user=request.user).values_list('id',flat=True))
            ids=[base_id for base_id in ids if str(base_id) in {str(item) for item in visible}]
        try: hits=retrieve(query,ids,top_k=int(request.data.get('top_k',5)),threshold=float(request.data.get('threshold',0)))
        except (ValueError,TypeError) as exc: raise ValidationError({'detail':str(exc)})
        return Response({'results':[hit.__dict__ for hit in hits]})
