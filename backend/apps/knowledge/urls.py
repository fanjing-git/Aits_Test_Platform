"""Knowledge API routes."""
from rest_framework.routers import DefaultRouter
from apps.knowledge.views import DocumentViewSet, KnowledgeBaseViewSet, KnowledgeSearchViewSet, QAPairViewSet
router=DefaultRouter()
router.register('knowledge-bases',KnowledgeBaseViewSet,basename='knowledge-base')
router.register('knowledge-documents',DocumentViewSet,basename='knowledge-document')
router.register('knowledge-qa',QAPairViewSet,basename='knowledge-qa')
router.register('knowledge-search',KnowledgeSearchViewSet,basename='knowledge-search')
urlpatterns=router.urls
