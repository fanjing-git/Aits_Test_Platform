from typing import Any
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework import status
from rest_framework.exceptions import APIException
import base64
import binascii
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from apps.projects.models import Project
from apps.projects.permissions import is_platform_admin, project_role
from apps.skills.models import Skill, SkillChain, SkillChainConfiguration, SkillChainNodeRun, SkillChainRun, SkillChainRunEvent, SkillInstallation, SkillPermissionAudit
from apps.skills.permissions import SkillAuditPermission, SkillChainConfigurationPermission, SkillChainPermission, SkillChainRunPermission, SkillInstallationPermission, SkillPermission, SkillPermissionError, can_read_governance_audit, enforce_skill_permission
from apps.skills.serializers import SkillChainConfigurationSerializer, SkillChainGovernanceAuditSerializer, SkillChainRunEventSerializer, SkillChainRunSerializer, SkillChainSerializer, SkillInstallationSerializer, SkillPermissionAuditSerializer, SkillSerializer
from apps.skills.installation import (
    SkillInstallationError,
    approve_installation,
    install_verified,
    request_installation,
    rollback_installation,
    uninstall_installation,
    verify_installation,
    verify_directory_installation,
)
from apps.skills.sources import SkillSourceError, discover_skill_manifest
from apps.skills.runtime import execute_skill, SkillRuntimeError
from apps.skills.execution import SkillChainExecutionError, SkillChainExecutionService
from apps.skills.services import (
    SkillChainLifecycleError,
    _chain_state,
    _configuration_state,
    chain_has_rollback_target,
    archive_skill_chain,
    create_skill_chain_draft,
    diff_skill_chain_versions,
    get_chain_history,
    get_configuration_history,
    record_governance_change,
    resolve_skill_chain_configuration,
    rollback_skill_chain_configuration,
    rollback_skill_chain_version,
    enable_skill_chain,
    publish_skill_chain,
    pause_skill_chain,
    verify_skill_chain,
    validate_chain_skill_references,
)

class SkillViewSet(viewsets.ModelViewSet):
    """CRUD and lifecycle API for global and project Skills."""
    serializer_class = SkillSerializer; permission_classes = (SkillPermission,)
    def get_queryset(self):
        """Return only global or project-visible Skills."""
        qs = Skill.objects.select_related('project','created_by')
        if is_platform_admin(self.request.user): return qs
        return qs.filter(Q(project__isnull=True) | Q(project__memberships__user=self.request.user)).distinct()
    def perform_update(self, serializer):
        """Enforce scoped management before saving changes."""
        self.check_object_permissions(self.request, self.get_object()); serializer.save()
    def perform_destroy(self, instance):
        """Enforce scoped management before deletion."""
        self.check_object_permissions(self.request, instance); instance.delete()
    @action(detail=True, methods=('post',))
    def toggle(self, request, pk=None):
        """Toggle enabled/disabled state with permission checks."""
        skill = self.get_object(); self.check_object_permissions(request, skill); skill.status = Skill.Status.DISABLED if skill.status == Skill.Status.ENABLED else Skill.Status.ENABLED; skill.save(update_fields=('status','updated_at')); return Response(self.get_serializer(skill).data)
    @action(detail=True, methods=('post',))
    def execute(self, request, pk=None):
        """Execute only through the controlled custom runtime boundary."""
        skill = self.get_object()
        self.check_object_permissions(request, skill)
        try:
            result = execute_skill(skill, request.data.get('input', request.data))
        except SkillRuntimeError as exc:
            return Response({'detail': str(exc), 'status': 'failed'}, status=400)
        return Response({'status': 'completed', 'result': result})



class SkillChainViewSet(viewsets.ModelViewSet):
    """Manage versioned Skill-chain blueprints and their scoped lifecycle."""

    serializer_class = SkillChainSerializer
    permission_classes = (SkillChainPermission,)

    def get_queryset(self) -> Any:
        """Return global and project-visible chain versions."""
        queryset = SkillChain.objects.select_related("project", "created_by").prefetch_related("configurations")
        if is_platform_admin(self.request.user):
            return queryset
        return queryset.filter(Q(project__isnull=True) | Q(project__memberships__user=self.request.user)).distinct()

    def _lifecycle_error(self, exc: SkillChainLifecycleError) -> Response:
        """Map a domain lifecycle conflict into a stable API response."""
        return Response(
            {"detail": str(exc), "reason_code": exc.reason_code},
            status=exc.http_status,
        )

    def _reason(self, request: Request) -> str:
        """Read a bounded operator reason without accepting actor identity fields."""
        value = request.data.get("reason", "") if isinstance(request.data, dict) else ""
        return value.strip()[:500] if isinstance(value, str) else ""

    def perform_create(self, serializer: Any) -> None:
        """Save the first draft and its baseline audit event atomically."""
        with transaction.atomic():
            chain = serializer.save(created_by=self.request.user)
            record_governance_change(
                actor=self.request.user,
                action="chain_create",
                chain=chain,
                reason="创建蓝图初始草稿版本",
            )

    def perform_update(self, serializer: Any) -> None:
        """Allow edits only to drafts and retain a scoped change event."""
        chain = serializer.instance
        if chain.status != SkillChain.Status.DRAFT:
            raise APIException({
                "detail": "已校验或发布的蓝图版本不可覆盖，请先派生新的草稿版本。",
                "reason_code": "version_immutable",
            })
        with transaction.atomic():
            before = _chain_state(chain)
            updated = serializer.save()
            record_governance_change(
                actor=self.request.user,
                action="chain_update",
                chain=updated,
                before_state=before,
                reason=self._reason(self.request),
            )

    def perform_destroy(self, instance: SkillChain) -> None:
        """Retain lifecycle history and refuse deletion of published or referenced versions."""
        if instance.status != SkillChain.Status.DRAFT or instance.published_at is not None:
            error = APIException({
                "detail": "已校验或发布的版本不能删除；请使用归档保留历史。",
                "reason_code": "version_immutable",
            })
            error.status_code = status.HTTP_409_CONFLICT
            raise error
        if instance.configurations.exists():
            error = APIException({
                "detail": "此蓝图仍被范围配置引用；请先调整范围配置，再归档蓝图。",
                "reason_code": "blueprint_in_use",
            })
            error.status_code = status.HTTP_409_CONFLICT
            raise error
        family = SkillChain.objects.filter(name=instance.name, project_id=instance.project_id).exclude(pk=instance.pk)
        if family.exists():
            error = APIException({
                "detail": "含有其他版本的蓝图不能删除；请使用归档保留版本历史。",
                "reason_code": "blueprint_has_history",
            })
            error.status_code = status.HTTP_409_CONFLICT
            raise error
        with transaction.atomic():
            record_governance_change(
                actor=self.request.user,
                action="chain_revoke",
                chain=instance,
                before_state=_chain_state(instance),
                reason=self._reason(self.request) or "撤销未发布的初始蓝图草稿",
            )
            instance.delete()

    @action(detail=True, methods=("get",))
    def versions(self, request: Request, pk: str | None = None) -> Response:
        """List all visible versions of the same scoped blueprint."""
        chain = self.get_object()
        family = self.get_queryset().filter(name=chain.name, project_id=chain.project_id).order_by("-created_at", "-id")
        return Response(self.get_serializer(family, many=True).data)

    @action(detail=True, methods=("get",))
    def diff(self, request: Request, pk: str | None = None) -> Response:
        """Compare this version with another version in the same blueprint family."""
        chain = self.get_object()
        target_id = request.query_params.get("compare_to", "")
        if not target_id:
            return Response({"compare_to": "请选择用于比较的蓝图版本。"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            other = self.get_queryset().get(pk=target_id)
        except (SkillChain.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return Response({"detail": "所选版本不存在或无权访问。"}, status=status.HTTP_404_NOT_FOUND)
        if other.name != chain.name or other.project_id != chain.project_id:
            return Response({"compare_to": "只能比较同一范围、同一名称下的蓝图版本。"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(diff_skill_chain_versions(other, chain))

    @action(detail=True, methods=("post",))
    def fork(self, request: Request, pk: str | None = None) -> Response:
        """Create a new editable draft from this version."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        draft = create_skill_chain_draft(
            chain,
            actor=request.user,
            reason=self._reason(request) or "从工作台派生新草稿版本",
        )
        return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",))
    def verify(self, request: Request, pk: str | None = None) -> Response:
        """Validate a draft and move it to the verified state."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        try:
            verified, issues = verify_skill_chain(chain, actor=request.user, reason=self._reason(request))
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        if issues:
            return Response(
                {"status": "blocked", "reason_code": "skill_not_compatible", "issues": issues},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(verified).data)

    @action(detail=True, methods=("post",))
    def publish(self, request: Request, pk: str | None = None) -> Response:
        """Publish only a verified version after checking its Skill references again."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        try:
            published, issues = publish_skill_chain(chain, actor=request.user, reason=self._reason(request))
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        if issues:
            return Response(
                {"status": "blocked", "reason_code": "skill_not_compatible", "issues": issues},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(published).data)

    @action(detail=True, methods=("post",))
    def enable(self, request: Request, pk: str | None = None) -> Response:
        """Enable one published version for new run selection."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        try:
            enabled, issues = enable_skill_chain(chain, actor=request.user, reason=self._reason(request))
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        if issues:
            return Response(
                {"status": "blocked", "reason_code": "skill_not_compatible", "issues": issues},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(enabled).data)

    @action(detail=True, methods=("post",))
    def pause(self, request: Request, pk: str | None = None) -> Response:
        """Pause selection for new runs without changing active runs."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        try:
            paused = pause_skill_chain(chain, actor=request.user, reason=self._reason(request))
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        return Response(self.get_serializer(paused).data)

    @action(detail=True, methods=("post",))
    def disable(self, request: Request, pk: str | None = None) -> Response:
        """Retain the old endpoint as an alias for the blueprint pause operation."""
        return self.pause(request, pk=pk)

    @action(detail=True, methods=("post",))
    def archive(self, request: Request, pk: str | None = None) -> Response:
        """Archive a non-enabled version while retaining its history."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        try:
            archived = archive_skill_chain(chain, actor=request.user, reason=self._reason(request))
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        return Response(self.get_serializer(archived).data)

    @action(detail=True, methods=("post",))
    def rollback(self, request: Request, pk: str | None = None) -> Response:
        """Create a new draft from the explicitly selected historical version."""
        chain = self.get_object()
        self.check_object_permissions(request, chain)
        if not chain_has_rollback_target(chain):
            return Response(
                {"detail": "暂无可回滚版本；需要先有更早的已发布版本。", "reason_code": "no_rollback_target"},
                status=status.HTTP_409_CONFLICT,
            )
        target_version_id = request.data.get("target_version_id") if isinstance(request.data, dict) else None
        if not target_version_id:
            return Response(
                {"target_version_id": "请选择要恢复内容的历史已发布版本。", "reason_code": "target_version_required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            draft = rollback_skill_chain_version(
                chain,
                target_version_id=target_version_id,
                actor=request.user,
                reason=self._reason(request),
            )
        except SkillChainLifecycleError as exc:
            return self._lifecycle_error(exc)
        return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("get",))
    def history(self, request: Request, pk: str | None = None) -> Response:
        """Return scoped audit history for all versions of this blueprint."""
        chain = self.get_object()
        if not can_read_governance_audit(request.user, chain):
            return Response({"detail": "当前账号没有该范围的蓝图审计读取权限。"}, status=status.HTTP_403_FORBIDDEN)
        return Response(SkillChainGovernanceAuditSerializer(get_chain_history(chain), many=True).data)


class SkillChainRunViewSet(viewsets.ModelViewSet):
    """Expose durable Skill-chain execution, controls and lineage."""

    serializer_class = SkillChainRunSerializer
    permission_classes = (SkillChainRunPermission,)
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self) -> Any:
        """Return only requester-owned or project-visible runs."""
        queryset = SkillChainRun.objects.select_related("chain", "configuration", "project", "requested_by").prefetch_related("nodes")
        if is_platform_admin(self.request.user):
            return queryset
        return queryset.filter(
            Q(requested_by=self.request.user)
            | Q(project__memberships__user=self.request.user)
        ).distinct()

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create one immutable run snapshot and queue its execution."""
        try:
            result = SkillChainExecutionService().start(user=request.user, payload=request.data)
        except SkillChainExecutionError as exc:
            return Response({"detail": exc.message, "reason_code": exc.code}, status=exc.http_status)
        serializer = self.get_serializer(result.run)
        return Response(serializer.data, status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)

    @action(detail=True, methods=("get",))
    def events(self, request: Request, pk: str | None = None) -> Response:
        """Return ordered lineage events for refresh recovery."""
        run = self.get_object()
        return Response(SkillChainRunEventSerializer(run.events.order_by("sequence"), many=True).data)

    def _control(self, request: Request, action_name: str) -> Response:
        """Run one permission-checked control operation."""
        run = self.get_object()
        self.check_object_permissions(request, run)
        service = SkillChainExecutionService()
        try:
            if action_name == "pause":
                updated = service.pause(run)
            elif action_name == "resume":
                value = request.data.get("input", {}) if isinstance(request.data, dict) else {}
                updated = service.resume(run, input_value=value if isinstance(value, dict) else {})
            elif action_name == "cancel":
                updated = service.cancel(run)
            else:
                node_id = str(request.data.get("node_id", "")).strip() if isinstance(request.data, dict) else ""
                if not node_id:
                    return Response({"node_id": "请提供要重试的节点标识。"}, status=status.HTTP_400_BAD_REQUEST)
                updated = service.retry_node(run, node_id)
        except SkillChainExecutionError as exc:
            return Response({"detail": exc.message, "reason_code": exc.code}, status=exc.http_status)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=("post",))
    def pause(self, request: Request, pk: str | None = None) -> Response:
        """Request a safe checkpoint pause."""
        return self._control(request, "pause")

    @action(detail=True, methods=("post",))
    def resume(self, request: Request, pk: str | None = None) -> Response:
        """Resume with the original execution snapshot."""
        return self._control(request, "resume")

    @action(detail=True, methods=("post",))
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Request cooperative cancellation."""
        return self._control(request, "cancel")

    @action(detail=True, methods=("post",), url_path="retry-node")
    def retry_node(self, request: Request, pk: str | None = None) -> Response:
        """Retry one failed node from the same frozen run snapshot."""
        return self._control(request, "retry-node")


class SkillChainConfigurationViewSet(viewsets.ModelViewSet):
    """Manage layer declarations, previews, rollback and governance history."""

    serializer_class = SkillChainConfigurationSerializer
    permission_classes = (SkillChainConfigurationPermission,)
    http_method_names = ("get", "post", "patch", "delete", "head", "options")

    def get_queryset(self) -> Any:
        """Return only configurations visible through their project or chain scope."""
        queryset = SkillChainConfiguration.objects.select_related("chain", "project", "created_by").prefetch_related("governance_audits")
        if is_platform_admin(self.request.user):
            return queryset
        return queryset.filter(
            Q(project__isnull=True, chain__project__isnull=True)
            | Q(project__memberships__user=self.request.user)
            | Q(chain__project__memberships__user=self.request.user)
        ).distinct()

    def perform_create(self, serializer: Any) -> None:
        """Persist and audit a newly created layer declaration atomically."""
        with transaction.atomic():
            configuration = serializer.save(created_by=self.request.user)
            record_governance_change(actor=self.request.user, action="create", configuration=configuration)

    def perform_update(self, serializer: Any) -> None:
        """Audit each configuration edit, enable and disable transition atomically."""
        with transaction.atomic():
            before = _configuration_state(serializer.instance)
            configuration = serializer.save()
            if before["enabled"] != configuration.enabled:
                action = "enable" if configuration.enabled else "disable"
            else:
                action = "update"
            record_governance_change(
                actor=self.request.user,
                action=action,
                configuration=configuration,
                before_state=before,
            )

    def perform_destroy(self, instance: SkillChainConfiguration) -> None:
        """Revoke a scope with a durable audit event before deleting its live record."""
        with transaction.atomic():
            record_governance_change(
                actor=self.request.user,
                action="revoke",
                configuration=instance,
                before_state=_configuration_state(instance),
                reason="配置已从工作台撤销",
            )
            instance.delete()

    @action(detail=True, methods=("post",))
    def rollback(self, request: Request, pk: str | None = None) -> Response:
        """Restore the prior audited state without deleting the current evidence."""
        configuration = self.get_object()
        self.check_object_permissions(request, configuration)
        if not can_read_governance_audit(request.user, configuration):
            return Response({"detail": "当前账号没有该范围的配置审计读取权限。"}, status=status.HTTP_403_FORBIDDEN)
        try:
            restored = rollback_skill_chain_configuration(
                configuration,
                actor=request.user,
                reason="用户在配置工作台发起回滚",
            )
        except SkillChainLifecycleError as exc:
            return Response(
                {"detail": str(exc), "reason_code": exc.reason_code},
                status=exc.http_status,
            )
        except ValueError as exc:
            return Response({"detail": str(exc), "reason_code": "rollback_unavailable"}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(restored).data)

    @action(detail=True, methods=("get",))
    def history(self, request: Request, pk: str | None = None) -> Response:
        """Return the retained audit trail for one visible configuration."""
        configuration = self.get_object()
        self.check_object_permissions(request, configuration)
        if not can_read_governance_audit(request.user, configuration):
            return Response({"detail": "当前账号没有该范围的配置审计读取权限。"}, status=status.HTTP_403_FORBIDDEN)
        return Response(SkillChainGovernanceAuditSerializer(
            get_configuration_history(configuration), many=True
        ).data)

    @action(detail=False, methods=("post",))
    def resolve(self, request: Request) -> Response:
        """Preview effective configuration for a project, feature and immediate choice."""
        payload = request.data if isinstance(request.data, dict) else {}
        project_key = payload.get("project") or None
        project = None
        if project_key:
            try:
                project = Project.objects.get(pk=project_key)
            except (Project.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                return Response({"project": "项目不存在。"}, status=status.HTTP_400_BAD_REQUEST)
            if not is_platform_admin(request.user) and project_role(request.user, project) is None:
                return Response({"detail": "当前账号无权查看此项目配置。"}, status=status.HTTP_403_FORBIDDEN)
        feature_key = payload.get("feature_key", "")
        request_key = payload.get("request_key", "")
        instant_chain_id = payload.get("instant_chain") or ""
        for key, value, maximum in (
            ("feature_key", feature_key, 120),
            ("request_key", request_key, 120),
        ):
            if not isinstance(value, str) or len(value) > maximum:
                return Response({key: f"最多允许 {maximum} 个字符。"}, status=status.HTTP_400_BAD_REQUEST)
        if instant_chain_id:
            try:
                chain = SkillChain.objects.get(pk=instant_chain_id)
            except (SkillChain.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                return Response({"instant_chain": "所选 Skill 链不存在。"}, status=status.HTTP_400_BAD_REQUEST)
            if chain.project_id and str(chain.project_id) != str(project.pk if project else ""):
                return Response({"detail": "即时选择的 Skill 链不属于当前项目。"}, status=status.HTTP_403_FORBIDDEN)
            if not is_platform_admin(request.user) and chain.project_id and project_role(request.user, chain.project) is None:
                return Response({"detail": "当前账号无权选择此 Skill 链。"}, status=status.HTTP_403_FORBIDDEN)
        result = resolve_skill_chain_configuration(
            project_id=project.pk if project else None,
            feature_key=feature_key,
            request_key=request_key,
            instant_chain_id=str(instant_chain_id),
        )
        return Response(result)


class SkillPermissionAuditViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only administrator view of permission decisions."""

    serializer_class = SkillPermissionAuditSerializer
    permission_classes = (SkillAuditPermission,)

    def get_queryset(self):
        """Return newest audit decisions with safe related labels."""
        queryset = SkillPermissionAudit.objects.select_related("installation", "actor")
        installation_id = self.request.query_params.get("installation")
        if installation_id:
            queryset = queryset.filter(installation_id=installation_id)
        return queryset


class SkillInstallationViewSet(viewsets.ModelViewSet):
    """Administrator API for controlled third-party Skill lifecycle actions."""

    serializer_class = SkillInstallationSerializer
    permission_classes = (SkillInstallationPermission,)
    http_method_names = ("get", "post", "head", "options")

    def get_queryset(self):
        """Return installation metadata with related user and Skill labels loaded."""
        return SkillInstallation.objects.select_related("skill", "requested_by", "approved_by", "installed_by")

    @staticmethod
    def _failure(exc: Exception) -> Response:
        """Return a safe client-facing lifecycle error."""
        return Response({"detail": str(exc), "status": "failed"}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        """Validate source metadata and create a pending installation request."""
        payload = request.data if isinstance(request.data, dict) else {}
        manifest = payload.get("manifest")
        address = payload.get("source_url") or payload.get("address")
        source = payload.get("source_type") or payload.get("source")
        try:
            normalized = discover_skill_manifest(address, manifest, source=source)
            installation = request_installation(normalized, requested_by=request.user)
        except (SkillSourceError, SkillInstallationError, TypeError, AttributeError) as exc:
            return self._failure(exc)
        return Response(self.get_serializer(installation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",))
    def verify(self, request, pk=None):
        """Verify a caller-provided file or Skills folder without executing code."""
        installation = self.get_object()
        artifact_files = request.data.get("artifact_files")
        if isinstance(artifact_files, list):
            try:
                updated = verify_directory_installation(
                    installation,
                    artifact_files,
                    artifact_version=request.data.get("artifact_version"),
                    observed_commit_hash=request.data.get("observed_commit_hash"),
                )
            except SkillInstallationError as exc:
                return self._failure(exc)
            return Response(self.get_serializer(updated).data)
        encoded = request.data.get("artifact_base64")
        if not isinstance(encoded, str) or not encoded:
            return self._failure(SkillInstallationError("artifact_base64 is required for controlled verification"))
        try:
            artifact = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            return self._failure(SkillInstallationError("artifact_base64 is invalid"))
        try:
            updated = verify_installation(
                installation,
                artifact,
                artifact_version=request.data.get("artifact_version"),
                observed_commit_hash=request.data.get("observed_commit_hash"),
            )
        except SkillInstallationError as exc:
            return self._failure(exc)
        return Response(self.get_serializer(updated).data)

    def _transition(self, request, action_name):
        installation = self.get_object()
        handlers = {
            "approve": lambda: approve_installation(installation, request.user),
            "install": lambda: install_verified(installation, request.user),
            "rollback": lambda: rollback_installation(installation, request.user),
            "uninstall": lambda: uninstall_installation(installation, request.user),
        }
        try:
            updated = handlers[action_name]()
        except SkillInstallationError as exc:
            return self._failure(exc)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        """Approve a verified installation request."""
        return self._transition(request, "approve")

    @action(detail=True, methods=("post",))
    def install(self, request, pk=None):
        """Mark an approved installation active without importing package code."""
        return self._transition(request, "install")

    @action(detail=True, methods=("post",))
    def rollback(self, request, pk=None):
        """Roll back a verified or installed package and disable its Skill."""
        return self._transition(request, "rollback")

    @action(detail=True, methods=("post",))
    def uninstall(self, request, pk=None):
        """Uninstall an active package while retaining its audit record."""
        return self._transition(request, "uninstall")

    @action(detail=True, methods=("post",))
    def invoke(self, request, pk=None):
        """Invoke an installed Skill only after its declared capability is authorized."""
        installation = self.get_object()
        permission = request.data.get("permission")
        payload = request.data.get("input", {})
        if not isinstance(permission, str) or not permission.strip():
            return self._failure(SkillPermissionError("permission is required for third-party Skill invocation"))
        if installation.skill_id is None:
            return self._failure(SkillInstallationError("installation has no controlled runtime binding"))
        try:
            enforce_skill_permission(installation, permission.strip(), actor=request.user, context={"input": payload})
            result = execute_skill(installation.skill, payload)
        except (SkillPermissionError, SkillRuntimeError) as exc:
            return self._failure(exc)
        return Response({"status": "completed", "result": result})
