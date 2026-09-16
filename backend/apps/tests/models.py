"""Persistence models for test cases and execution records."""

from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def validate_json_array(value: Any) -> None:
    """Require a JSON array for ordered test steps or assertion records."""
    if not isinstance(value, list):
        raise ValidationError("该字段必须是 JSON 数组。")


def validate_json_object(value: Any) -> None:
    """Require a JSON object for configuration and summary records."""
    if not isinstance(value, dict):
        raise ValidationError("该字段必须是 JSON 对象。")


class TestCase(models.Model):
    """Store a project-scoped functional or interface test case."""

    class Priority(models.TextChoices):
        """Supported execution priorities."""

        P0 = "P0", "P0"
        P1 = "P1", "P1"
        P2 = "P2", "P2"
        P3 = "P3", "P3"

    class CaseType(models.TextChoices):
        """Supported case categories from the product contract."""

        FUNCTION = "function", "功能"
        BOUNDARY = "boundary", "边界"
        EXCEPTION = "exception", "异常"
        SECURITY = "security", "安全"
        API = "api", "接口"
        AI = "ai", "AI"
        UI = "ui", "界面"
        APP = "app", "应用"
        PERF = "perf", "性能"
        LINKAGE = "linkage", "业务链路"

    class AutomationDifficulty(models.TextChoices):
        """Difficulty labels used for automation planning."""

        LOW = "low", "低"
        MEDIUM = "medium", "中"
        HIGH = "high", "高"

    class AutomationTech(models.TextChoices):
        """Supported automation technology labels."""

        PYTEST = "pytest", "pytest"
        PLAYWRIGHT = "playwright", "Playwright"
        APPIUM = "appium", "Appium"
        LOCUST = "locust", "Locust"
        JMETER = "jmeter", "JMeter"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="test_cases",
        verbose_name="项目",
    )
    case_id = models.CharField("用例编号", max_length=50, unique=True)
    title = models.CharField("用例标题", max_length=500)
    precondition = models.TextField("前置条件", blank=True)
    steps = models.JSONField("测试步骤", default=list, blank=True, validators=[validate_json_array])
    input_data = models.JSONField("输入数据", default=dict, blank=True, validators=[validate_json_object])
    expected_result = models.TextField("预期结果")
    priority = models.CharField("优先级", max_length=10, choices=Priority.choices, default=Priority.P1)
    case_type = models.CharField("用例类型", max_length=50, choices=CaseType.choices, default=CaseType.FUNCTION)
    is_automation = models.BooleanField("是否自动化", default=False)
    automation_difficulty = models.CharField(
        "自动化难度", max_length=10, choices=AutomationDifficulty.choices, blank=True
    )
    automation_tech = models.CharField(
        "自动化技术", max_length=50, choices=AutomationTech.choices, blank=True
    )
    requirement_mapping = models.JSONField(
        "需求映射", default=dict, blank=True, validators=[validate_json_object]
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        """Keep the database representation aligned with the architecture."""

        verbose_name = "测试用例"
        verbose_name_plural = "测试用例"
        ordering = ("project__name", "case_id")
        indexes = [
            models.Index(fields=("project", "case_type", "priority"), name="tests_tc_project_type_prio_idx")
        ]

    def __str__(self) -> str:
        """Return a stable, human-readable case label."""
        return f"{self.project.name} / {self.case_id} / {self.title}"

    def clean(self) -> None:
        """Validate JSON shapes and complete automation metadata."""
        super().clean()
        if self.steps is None:
            self.steps = []
        if self.input_data is None:
            self.input_data = {}
        if self.requirement_mapping is None:
            self.requirement_mapping = {}
        errors: dict[str, str] = {}
        if not isinstance(self.steps, list):
            errors["steps"] = "测试步骤必须是 JSON 数组。"
        if not isinstance(self.input_data, dict):
            errors["input_data"] = "输入数据必须是 JSON 对象。"
        if not isinstance(self.requirement_mapping, dict):
            errors["requirement_mapping"] = "需求映射必须是 JSON 对象。"
        if self.is_automation and not self.automation_difficulty:
            errors["automation_difficulty"] = "自动化用例必须填写自动化难度。"
        if self.is_automation and not self.automation_tech:
            errors["automation_tech"] = "自动化用例必须填写自动化技术。"
        if errors:
            raise ValidationError(errors)


class TestRun(models.Model):
    """Represent one execution request for selected project test cases."""

    class Mode(models.TextChoices):
        """Execution modes reserved for the executor tasks."""

        IMMEDIATE = "immediate", "立即执行"
        SCRIPT = "script", "脚本执行"
        FULL = "full", "全量执行"

    class Status(models.TextChoices):
        """Lifecycle states for a run."""

        PENDING = "pending", "待执行"
        RUNNING = "running", "执行中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="test_runs", verbose_name="项目"
    )
    environment = models.ForeignKey(
        "environments.Environment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_runs",
        verbose_name="执行环境",
    )
    name = models.CharField("执行名称", max_length=200)
    mode = models.CharField("执行模式", max_length=20, choices=Mode.choices, default=Mode.IMMEDIATE)
    status = models.CharField("执行状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    test_cases = models.ManyToManyField(TestCase, related_name="test_runs", blank=True, verbose_name="测试用例")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_test_runs",
        verbose_name="创建人",
    )
    execution_config = models.JSONField("执行配置", default=dict, blank=True, validators=[validate_json_object])
    summary = models.JSONField("执行摘要", default=dict, blank=True, validators=[validate_json_object])
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        """Index common project and status queries."""

        verbose_name = "测试执行"
        verbose_name_plural = "测试执行"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("project", "status", "created_at"), name="tests_run_project_status_idx")]

    def __str__(self) -> str:
        """Return the execution name with its current state."""
        return f"{self.project.name} / {self.name} ({self.status})"

    def clean(self) -> None:
        """Prevent selecting an environment belonging to another project."""
        super().clean()
        if self.execution_config is None:
            self.execution_config = {}
        if self.summary is None:
            self.summary = {}
        if self.environment_id and self.environment.project_id != self.project_id:
            raise ValidationError({"environment": "执行环境必须属于同一个项目。"})
        if not isinstance(self.execution_config, dict):
            raise ValidationError({"execution_config": "执行配置必须是 JSON 对象。"})
        if not isinstance(self.summary, dict):
            raise ValidationError({"summary": "执行摘要必须是 JSON 对象。"})

    def attach_test_cases(self, *test_cases: TestCase) -> None:
        """Attach saved cases after enforcing the project boundary."""
        if not self.pk:
            raise ValueError("测试执行必须先保存后才能关联测试用例。")
        invalid = [case.case_id for case in test_cases if case.project_id != self.project_id]
        if invalid:
            raise ValidationError({"test_cases": f"测试用例不属于当前项目：{', '.join(invalid)}。"})
        self.test_cases.add(*test_cases)


class TestResult(models.Model):
    """Store one case result without persisting sensitive raw responses."""

    class Status(models.TextChoices):
        """Result states reported by executors."""

        PENDING = "pending", "待执行"
        RUNNING = "running", "执行中"
        PASSED = "passed", "通过"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "跳过"
        ERROR = "error", "错误"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(TestRun, on_delete=models.CASCADE, related_name="results", verbose_name="测试执行")
    test_case = models.ForeignKey(TestCase, on_delete=models.CASCADE, related_name="results", verbose_name="测试用例")
    status = models.CharField("结果状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    duration_ms = models.PositiveIntegerField("耗时毫秒", null=True, blank=True)
    status_code = models.PositiveSmallIntegerField(
        "响应状态码", null=True, blank=True, validators=[MinValueValidator(100), MaxValueValidator(599)]
    )
    response_summary = models.JSONField("响应摘要", default=dict, blank=True, validators=[validate_json_object])
    assertions = models.JSONField("断言结果", default=list, blank=True, validators=[validate_json_array])
    error_code = models.CharField("错误编码", max_length=80, blank=True)
    error_message = models.TextField("错误信息", blank=True)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        """Prevent duplicate results for one case in one run."""

        verbose_name = "测试结果"
        verbose_name_plural = "测试结果"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("run", "test_case"), name="tests_result_run_case_uniq")
        ]
        indexes = [models.Index(fields=("run", "status"), name="tests_result_run_status_idx")]

    def __str__(self) -> str:
        """Return a compact result label."""
        return f"{self.run.name} / {self.test_case.case_id} ({self.status})"

    def clean(self) -> None:
        """Enforce project isolation and result payload shapes."""
        super().clean()
        if self.response_summary is None:
            self.response_summary = {}
        if self.assertions is None:
            self.assertions = []
        if self.run_id and self.test_case_id and self.run.project_id != self.test_case.project_id:
            raise ValidationError({"test_case": "测试结果的用例必须属于执行所在项目。"})
        if not isinstance(self.response_summary, dict):
            raise ValidationError({"response_summary": "响应摘要必须是 JSON 对象。"})
        if not isinstance(self.assertions, list):
            raise ValidationError({"assertions": "断言结果必须是 JSON 数组。"})


class Evaluation(models.Model):
    """Store rule, model, or human evaluation for an execution result."""

    class Evaluator(models.TextChoices):
        """Evaluation sources supported by the product."""

        RULE = "rule", "规则"
        LLM = "llm", "模型"
        MANUAL = "manual", "人工"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    run = models.ForeignKey(TestRun, on_delete=models.CASCADE, related_name="evaluations", verbose_name="测试执行")
    result = models.ForeignKey(
        TestResult,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
        verbose_name="测试结果",
    )
    evaluator = models.CharField("评价来源", max_length=20, choices=Evaluator.choices, default=Evaluator.RULE)
    score = models.DecimalField(
        "评分", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    grade = models.CharField("等级", max_length=20, blank=True)
    dimensions = models.JSONField("评价维度", default=dict, blank=True, validators=[validate_json_object])
    recommendations = models.JSONField("改进建议", default=list, blank=True, validators=[validate_json_array])
    summary = models.TextField("评价摘要", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        """Index evaluation lookups by execution and source."""

        verbose_name = "测试评价"
        verbose_name_plural = "测试评价"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("run", "evaluator"), name="tests_eval_run_evaluator_idx")]

    def __str__(self) -> str:
        """Return the evaluation source and execution name."""
        return f"{self.run.name} / {self.evaluator}"

    def clean(self) -> None:
        """Ensure an optional result belongs to the evaluated execution."""
        super().clean()
        if self.dimensions is None:
            self.dimensions = {}
        if self.recommendations is None:
            self.recommendations = []
        if self.result_id and self.run_id and self.result.run_id != self.run_id:
            raise ValidationError({"result": "评价结果必须属于同一个测试执行。"})
        if not isinstance(self.dimensions, dict):
            raise ValidationError({"dimensions": "评价维度必须是 JSON 对象。"})
        if not isinstance(self.recommendations, list):
            raise ValidationError({"recommendations": "改进建议必须是 JSON 数组。"})
