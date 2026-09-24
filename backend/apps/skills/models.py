"""Persistent Skill definitions and trigger contracts."""
from typing import Any
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.skills.contracts import SkillChainContractError, legacy_skill_ids, validate_skill_chain_definition

def validate_object(value: Any) -> None:
    """Require a JSON object."""
    if not isinstance(value, dict): raise ValidationError("技能配置必须是 JSON 对象。")

def validate_string_list(value: Any) -> None:
    """Require unique non-empty strings."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value): raise ValidationError("技能列表必须是非空字符串数组。")
    if len(value) != len(set(value)): raise ValidationError("技能列表不能包含重复项。")


def validate_chain_definition(value: Any) -> None:
    """Adapt the public Skill-chain contract to Django validation."""
    try:
        validate_skill_chain_definition(value)
    except SkillChainContractError as exc:
        raise ValidationError(str(exc)) from exc


def validate_legacy_skill_ids(value: Any) -> None:
    """Validate compatibility metadata without treating it as a chain plan."""
    try:
        legacy_skill_ids(value)
    except SkillChainContractError as exc:
        raise ValidationError(str(exc)) from exc

class Skill(models.Model):
    """A versioned global or project-scoped Skill definition."""
    class Category(models.TextChoices):
        CORE = "core", "核心"; SPECIALIZED = "specialized", "专业"; AUXILIARY = "auxiliary", "辅助"; CUSTOM = "custom", "自定义"
    class Status(models.TextChoices):
        ENABLED = "enabled", "启用"; DISABLED = "disabled", "停用"
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="skills", verbose_name="项目")
    name = models.CharField("技能名称", max_length=100)
    version = models.CharField("版本", max_length=30, default="1.0.0")
    description = models.TextField("描述", blank=True)
    category = models.CharField("分类", max_length=20, choices=Category.choices, default=Category.CORE, db_index=True)
    triggers = models.JSONField("触发条件", default=dict, validators=[validate_object])
    capabilities = models.JSONField("能力列表", default=list, validators=[validate_string_list])
    tools = models.JSONField("所需工具", default=list, validators=[validate_string_list])
    knowledge = models.JSONField("所需知识", default=list, validators=[validate_string_list])
    input_schema = models.JSONField("输入定义", default=dict, validators=[validate_object])
    output_schema = models.JSONField("输出定义", default=dict, validators=[validate_object])
    runtime_key = models.CharField("运行时绑定", max_length=100, default="configured", blank=True)
    timeout_seconds = models.PositiveIntegerField("超时秒数", default=30)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.ENABLED, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_skills", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True); updated_at = models.DateTimeField("更新时间", auto_now=True)
    class Meta:
        verbose_name = "技能"; verbose_name_plural = "技能"; ordering = ("name", "version")
        constraints = [models.UniqueConstraint(fields=("project", "name", "version"), name="skills_scope_name_version_uniq")]
    def __str__(self) -> str: return f"{self.name} v{self.version}"
    def clean(self) -> None:
        """Enforce custom Skill project scope and JSON shapes."""
        super().clean()
        if self.category == self.Category.CUSTOM and self.project_id is None: raise ValidationError({"project": "自定义技能必须关联项目。"})
        if self.category != self.Category.CUSTOM and self.project_id is not None: raise ValidationError({"project": "内置技能不能绑定项目。"})
        for field in ("triggers", "input_schema", "output_schema"): validate_object(getattr(self, field))
        for field in ("capabilities", "tools", "knowledge"): validate_string_list(getattr(self, field))



class SkillChain(models.Model):
    """Versioned, executable Skill-chain contract owned by a scope."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        VERIFIED = "verified", "已校验"
        PUBLISHED = "published", "已发布"
        ENABLED = "enabled", "启用"
        PAUSED = "paused", "已暂停"
        ARCHIVED = "archived", "已归档"
        # Keep legacy states readable while old clients and data are migrated.
        DISABLED = "disabled", "停用"
        ROLLED_BACK = "rolled_back", "已回滚"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="skill_chains", verbose_name="项目")
    name = models.CharField("链名称", max_length=120)
    version = models.CharField("链版本", max_length=30, default="1.0.0")
    description = models.TextField("链说明", blank=True)
    schema_version = models.CharField("契约版本", max_length=40, default="skill-chain-v1")
    definition = models.JSONField("链定义", validators=[validate_chain_definition])
    legacy_skill_ids = models.JSONField("旧 Skill ID 兼容信息", default=list, blank=True, validators=[validate_legacy_skill_ids])
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    published_at = models.DateTimeField("发布时间", null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_skill_chains", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "Skill 链"
        verbose_name_plural = "Skill 链"
        ordering = ("name", "version")
        constraints = [models.UniqueConstraint(fields=("project", "name", "version"), name="skills_chain_scope_name_version_uniq")]

    def __str__(self) -> str:
        """Return a concise chain label."""
        return f"{self.name} v{self.version}"

    def clean(self) -> None:
        """Enforce scope, version, schema and canonical definition rules."""
        super().clean()
        if not self.version.strip() or any(character.isspace() for character in self.version):
            raise ValidationError({"version": "链版本必须是无空格的非空字符串。"})
        try:
            self.definition = validate_skill_chain_definition(self.definition)
            self.legacy_skill_ids = legacy_skill_ids(self.legacy_skill_ids)
        except SkillChainContractError as exc:
            raise ValidationError({"definition": str(exc)}) from exc


class SkillChainConfiguration(models.Model):
    """Persist one layer-specific reference to a complete Skill-chain contract."""

    class Layer(models.TextChoices):
        GLOBAL = "global", "全局默认"
        PROJECT = "project", "项目覆盖"
        FEATURE = "feature", "功能覆盖"
        INSTANT = "instant", "即时指定"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    chain = models.ForeignKey(SkillChain, on_delete=models.CASCADE, related_name="configurations", verbose_name="Skill 链")
    layer = models.CharField("配置层级", max_length=20, choices=Layer.choices, db_index=True)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="skill_chain_configurations", verbose_name="项目")
    feature_key = models.CharField("功能标识", max_length=120, blank=True)
    request_key = models.CharField("即时请求标识", max_length=120, blank=True)
    version_lock = models.CharField("锁定版本", max_length=30, blank=True)
    overrides = models.JSONField("层级覆盖", default=dict, validators=[validate_object], blank=True)
    configuration_snapshot = models.JSONField("配置快照", default=dict, validators=[validate_object], blank=True)
    enabled = models.BooleanField("是否生效", default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_skill_chain_configurations", verbose_name="创建者")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "Skill 链配置"
        verbose_name_plural = "Skill 链配置"
        ordering = ("layer", "-updated_at")
        constraints = [models.UniqueConstraint(fields=("chain", "layer", "project", "feature_key", "request_key"), name="skills_chain_config_scope_uniq")]

    def __str__(self) -> str:
        """Return the layer and chain label."""
        return f"{self.get_layer_display()} / {self.chain}"

    def clean(self) -> None:
        """Ensure each configuration layer carries only its intended scope."""
        super().clean()
        if self.layer == self.Layer.GLOBAL and (self.project_id or self.feature_key or self.request_key):
            raise ValidationError("全局配置不能带项目、功能或即时请求范围。")
        if self.layer == self.Layer.PROJECT and (not self.project_id or self.feature_key or self.request_key):
            raise ValidationError("项目配置必须绑定项目且不能带功能或即时请求范围。")
        if self.layer == self.Layer.FEATURE and (not self.project_id or not self.feature_key or self.request_key):
            raise ValidationError("功能配置必须绑定项目和功能标识。")
        if self.layer == self.Layer.INSTANT and (self.feature_key or not self.request_key):
            raise ValidationError("即时配置必须带请求标识且不能带功能标识。")
        if self.chain_id and self.chain.project_id:
            if self.layer == self.Layer.GLOBAL:
                raise ValidationError({"layer": "项目链不能注册为全局默认配置。"})
            if self.project_id and self.project_id != self.chain.project_id:
                raise ValidationError({"project": "配置项目必须与项目链所属项目一致。"})
        if self.version_lock and any(character.isspace() for character in self.version_lock):
            raise ValidationError({"version_lock": "锁定版本不能包含空格。"})

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist a fresh layer snapshot with every configuration change."""
        preserve_snapshot = kwargs.pop("preserve_snapshot", False)
        if self.chain_id and not preserve_snapshot:
            from apps.skills.services import build_skill_chain_configuration_snapshot

            self.configuration_snapshot = build_skill_chain_configuration_snapshot(
                chain=self.chain,
                layer=self.layer,
                project_id=self.project_id,
                feature_key=self.feature_key,
                request_key=self.request_key,
                version_lock=self.version_lock,
                overrides=self.overrides,
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"configuration_snapshot", "updated_at"}
        super().save(*args, **kwargs)


class SkillChainRun(models.Model):
    """Persist one authoritative execution of a Skill-chain snapshot."""

    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        RUNNING = "running", "运行中"
        PAUSE_REQUESTED = "pause_requested", "请求暂停"
        PAUSED = "paused", "已暂停"
        WAITING_HUMAN = "waiting_human", "等待人工"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"
        TIMED_OUT = "timed_out", "已超时"
        CANCEL_REQUESTED = "cancel_requested", "请求取消"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    chain = models.ForeignKey(SkillChain, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs", verbose_name="蓝图")
    configuration = models.ForeignKey("skills.SkillChainConfiguration", null=True, blank=True, on_delete=models.SET_NULL, related_name="runs", verbose_name="生效配置")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="skill_chain_runs", verbose_name="项目")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_skill_chain_runs", verbose_name="发起人")
    idempotency_key = models.CharField("幂等键", max_length=128, null=True, blank=True)
    status = models.CharField("运行状态", max_length=30, choices=Status.choices, default=Status.PENDING, db_index=True)
    input_snapshot = models.JSONField("输入快照", default=dict, validators=[validate_object])
    execution_snapshot = models.JSONField("执行快照", default=dict, validators=[validate_object])
    output_snapshot = models.JSONField("输出快照", default=dict, validators=[validate_object], blank=True)
    current_node_id = models.CharField("当前节点", max_length=80, blank=True)
    checkpoint_node_id = models.CharField("安全检查点", max_length=80, blank=True)
    control_request = models.CharField("控制请求", max_length=30, blank=True)
    error_code = models.CharField("错误编码", max_length=60, blank=True)
    error_message = models.TextField("错误信息", blank=True)
    attempt = models.PositiveIntegerField("运行尝试次数", default=1)
    task_id = models.CharField("任务编号", max_length=150, blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "Skill 链运行"
        verbose_name_plural = "Skill 链运行"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("requested_by", "idempotency_key"), name="skills_run_request_idempotency_uniq"),
        ]


class SkillChainNodeRun(models.Model):
    """Persist one node's state and snapshots within a parent run."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(SkillChainRun, on_delete=models.CASCADE, related_name="nodes", verbose_name="父运行")
    node_id = models.CharField("节点标识", max_length=80)
    position = models.PositiveIntegerField("节点顺序", default=0)
    node_type = models.CharField("节点类型", max_length=30)
    status = models.CharField("节点状态", max_length=30, default="pending", db_index=True)
    definition_snapshot = models.JSONField("节点定义快照", default=dict, validators=[validate_object])
    input_snapshot = models.JSONField("节点输入快照", default=dict, validators=[validate_object], blank=True)
    output_snapshot = models.JSONField("节点输出快照", default=dict, validators=[validate_object], blank=True)
    attempt = models.PositiveIntegerField("节点尝试次数", default=0)
    max_retries = models.PositiveIntegerField("最大重试次数", default=0)
    checkpoint_safe = models.BooleanField("是否安全检查点", default=False)
    error_code = models.CharField("错误编码", max_length=60, blank=True)
    error_message = models.TextField("错误信息", blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "Skill 链节点运行"
        verbose_name_plural = "Skill 链节点运行"
        ordering = ("position", "created_at")
        constraints = [
            models.UniqueConstraint(fields=("run", "node_id"), name="skills_node_run_unique_node"),
        ]


class SkillChainRunEvent(models.Model):
    """Append-only lineage event for refresh, recovery and audit evidence."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(SkillChainRun, on_delete=models.CASCADE, related_name="events", verbose_name="父运行")
    node = models.ForeignKey(SkillChainNodeRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="events", verbose_name="节点")
    sequence = models.PositiveIntegerField("序号")
    event_type = models.CharField("事件类型", max_length=40)
    from_status = models.CharField("原状态", max_length=30, blank=True)
    to_status = models.CharField("目标状态", max_length=30, blank=True)
    node_key = models.CharField("节点标识", max_length=80, blank=True)
    payload = models.JSONField("事件内容", default=dict, validators=[validate_object], blank=True)
    created_at = models.DateTimeField("发生时间", auto_now_add=True)

    class Meta:
        verbose_name = "Skill 链运行事件"
        verbose_name_plural = "Skill 链运行事件"
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(fields=("run", "sequence"), name="skills_run_event_sequence_uniq"),
        ]


class SkillChainGovernanceAudit(models.Model):
    """Retain configuration and chain lifecycle changes for review and rollback."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    chain = models.ForeignKey(
        SkillChain,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="governance_audits",
        verbose_name="Skill 链",
    )
    configuration = models.ForeignKey(
        SkillChainConfiguration,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="governance_audits",
        verbose_name="Skill 链配置",
    )
    object_id = models.UUIDField("对象编号", db_index=True)
    action = models.CharField("操作", max_length=30, db_index=True)
    before_state = models.JSONField("变更前快照", default=dict, blank=True)
    after_state = models.JSONField("变更后快照", default=dict, blank=True)
    reason = models.CharField("操作说明", max_length=500, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="skill_chain_governance_audits",
        verbose_name="操作人",
    )
    actor_display_name = models.CharField("操作人显示名快照", max_length=150, blank=True)
    actor_role = models.CharField("操作人角色快照", max_length=40, blank=True)
    actor_scope = models.JSONField("操作人授权范围快照", default=dict, blank=True)
    result = models.CharField("操作结果", max_length=20, default="success")
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        verbose_name = "Skill 链治理审计"
        verbose_name_plural = "Skill 链治理审计"
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        """Return a concise audit label."""
        return f"{self.action}:{self.object_id}"

class SkillInstallation(models.Model):
    """Auditable record for a verified third-party Skill installation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        INSTALLED = "installed", "Installed"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"
        UNINSTALLED = "uninstalled", "Uninstalled"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    skill = models.ForeignKey("skills.Skill", null=True, blank=True, on_delete=models.SET_NULL, related_name="installations")
    source_type = models.CharField("Source type", max_length=20)
    source_url = models.CharField("Source address", max_length=500)
    version = models.CharField("Locked version", max_length=30)
    manifest = models.JSONField("Normalized manifest", default=dict, validators=[validate_object])
    commit_hash = models.CharField("Commit hash", max_length=128, blank=True)
    file_hash = models.CharField("File hash", max_length=128, blank=True)
    status = models.CharField("Installation status", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    error_message = models.TextField("Failure reason", blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_skill_installations")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_skill_installations")
    approved_at = models.DateTimeField(null=True, blank=True)
    installed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="installed_skill_installations")
    installed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Keep the newest installation attempts easy to inspect."""

        ordering = ("-created_at",)
        indexes = [models.Index(fields=("source_type", "source_url", "version"), name="skills_install_source_idx")]

    def __str__(self) -> str:
        """Return a concise audit label."""
        return f"{self.source_type}:{self.version} ({self.status})"


class SkillPermissionAudit(models.Model):
    """Record every third-party Skill permission decision."""

    installation = models.ForeignKey(SkillInstallation, on_delete=models.CASCADE, related_name="permission_audits")
    permission = models.CharField("Permission", max_length=40)
    allowed = models.BooleanField(default=False)
    reason = models.CharField("Decision reason", max_length=200)
    context_keys = models.JSONField("Context keys", default=list, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="skill_permission_audits")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Keep permission decisions in chronological order for audit review."""

        ordering = ("-created_at",)
        indexes = [models.Index(fields=("installation", "permission", "created_at"), name="skills_perm_audit_idx")]

    def __str__(self) -> str:
        """Return a concise permission decision label."""
        return f"{self.permission}: {'allowed' if self.allowed else 'denied'}"
