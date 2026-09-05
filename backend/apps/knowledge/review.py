"""Human review transitions for knowledge documents and QA pairs."""
from typing import Any
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.knowledge.models import Document, KnowledgeBase, QAPair, ReviewStatus
from apps.projects.models import ProjectMember
from apps.projects.permissions import is_platform_admin, project_role
from apps.users.permissions import PlatformAction, get_permission_scope, get_user_role


def can_review(user: Any, knowledge_base: KnowledgeBase) -> bool:
    """Require review capability and project management scope for project data."""
    if is_platform_admin(user):
        return True
    if get_permission_scope(get_user_role(user), PlatformAction.REVIEW_KNOWLEDGE) is None:
        return False
    return knowledge_base.project_id is None or project_role(user, knowledge_base.project) in {ProjectMember.Role.OWNER, ProjectMember.Role.MANAGER}


@transaction.atomic
def review_asset(asset: Document | QAPair, actor: Any, decision: str, note: str = "") -> Document | QAPair:
    """Apply an auditable review decision while preserving content immutability."""
    if not can_review(actor, asset.knowledge_base):
        raise PermissionDenied("当前角色无权审核此知识内容。")
    try:
        status = ReviewStatus(decision)
    except ValueError as exc:
        raise ValidationError({"review_status": "审核状态必须是 approved、rejected 或 paused。"}) from exc
    if isinstance(asset, Document) and status == ReviewStatus.APPROVED and asset.status != Document.Status.READY:
        raise ValidationError({"review_status": "文档完成解析后才能审核通过。"})
    if status == ReviewStatus.PENDING:
        raise ValidationError({"review_status": "不能将内容重新设置为待审核，请创建新的审核版本。"})
    if not isinstance(note, str) or len(note) > 500:
        raise ValidationError({"review_note": "审核备注最多500个字符。"})
    locked = asset.__class__.objects.select_for_update().get(pk=asset.pk)
    locked.review_status = status
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    if isinstance(locked, Document):
        locked.review_note = note
        locked.save(update_fields=("review_status", "review_note", "reviewed_by", "reviewed_at", "updated_at"))
    else:
        locked.save(update_fields=("review_status", "reviewed_by", "reviewed_at", "updated_at"))
    return locked
