from rest_framework.routers import DefaultRouter
from apps.skills.views import SkillPermissionAuditViewSet, SkillViewSet
from django.urls import path

router = DefaultRouter(); router.register('skills', SkillViewSet, basename='skill')
urlpatterns = [
    path("skills/permission-audits/", SkillPermissionAuditViewSet.as_view({"get": "list"}), name="skill-permission-audits"),
] + router.urls
