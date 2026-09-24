from rest_framework.routers import DefaultRouter
from apps.skills.views import SkillChainConfigurationViewSet, SkillChainRunViewSet, SkillChainViewSet, SkillInstallationViewSet, SkillPermissionAuditViewSet, SkillViewSet
from django.urls import path

router = DefaultRouter()
router.register('skills/installations', SkillInstallationViewSet, basename='skill-installation')
router.register('skill-chains', SkillChainViewSet, basename='skill-chain')
router.register('skill-chain-configurations', SkillChainConfigurationViewSet, basename='skill-chain-configuration')
router.register('skill-chain-runs', SkillChainRunViewSet, basename='skill-chain-run')
router.register('skills', SkillViewSet, basename='skill')
urlpatterns = [
    path("skills/permission-audits/", SkillPermissionAuditViewSet.as_view({"get": "list"}), name="skill-permission-audits"),
] + router.urls
