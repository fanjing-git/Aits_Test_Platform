"""Safe REST representations for test cases, runs, and results."""

from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from rest_framework import serializers

from apps.environments.models import Environment
from apps.projects.models import Project
from apps.tests.models import TestCase, TestResult, TestRun
from apps.tests.services import create_test_run


class TestCaseSerializer(serializers.ModelSerializer):
    """Expose executable case structure while keeping project ownership stable."""

    project_id = serializers.PrimaryKeyRelatedField(source="project", queryset=Project.objects.all(), write_only=True, required=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    case_type_label = serializers.CharField(source="get_case_type_display", read_only=True)
    automation_difficulty_label = serializers.CharField(source="get_automation_difficulty_display", read_only=True)
    automation_tech_label = serializers.CharField(source="get_automation_tech_display", read_only=True)

    class Meta:
        """Keep timestamps and database identity read-only."""

        model = TestCase
        fields = (
            "id", "project_id", "project_name", "case_id", "title", "precondition", "steps",
            "input_data", "expected_result", "priority", "priority_label", "case_type", "case_type_label",
            "is_automation", "automation_difficulty", "automation_difficulty_label", "automation_tech",
            "automation_tech_label", "requirement_mapping", "created_at",
        )
        read_only_fields = (
            "id", "project_name", "priority_label", "case_type_label", "automation_difficulty_label",
            "automation_tech_label", "created_at",
        )
        validators = []

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate JSON shape through the model before the service persists it."""
        if self.instance and "project_id" in self.initial_data and str(self.initial_data["project_id"]) != str(self.instance.project_id):
            raise serializers.ValidationError({"project_id": "测试用例不能移动到其他项目。"})
        project = attrs.get("project") or getattr(self.instance, "project", None)
        existing = {
            key: getattr(self.instance, key)
            for key in ("case_id", "title", "precondition", "steps", "input_data", "expected_result", "priority", "case_type", "is_automation", "automation_difficulty", "automation_tech", "requirement_mapping")
        } if self.instance else {}
        existing.update({key: value for key, value in attrs.items() if key != "project"})
        probe = TestCase(project=project, **existing)
        if self.instance:
            probe.pk = self.instance.pk
        try:
            probe.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TestCase:
        """Persist a validated case with normal model validation."""
        case = TestCase.objects.create(**validated_data)
        case.full_clean()
        return case

    def update(self, instance: TestCase, validated_data: dict[str, Any]) -> TestCase:
        """Update only fields within the existing project boundary."""
        validated_data.pop("project", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        return instance


class TestResultSerializer(serializers.ModelSerializer):
    """Expose safe result metadata and never raw response bodies."""

    test_case_id = serializers.UUIDField(source="test_case.id", read_only=True)
    case_id = serializers.CharField(source="test_case.case_id", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        """All result fields are read-only because executors own result writes."""

        model = TestResult
        fields = (
            "id", "test_case_id", "case_id", "status", "status_label", "duration_ms", "status_code",
            "response_summary", "assertions", "error_code", "error_message", "started_at", "completed_at",
            "created_at",
        )
        read_only_fields = fields


class TestRunSerializer(serializers.ModelSerializer):
    """Create project runs from selected case IDs and return nested safe results."""

    project_id = serializers.PrimaryKeyRelatedField(source="project", queryset=Project.objects.all(), write_only=True, required=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    environment_id = serializers.PrimaryKeyRelatedField(source="environment", queryset=Environment.objects.all(), allow_null=True, required=False)
    environment_name = serializers.CharField(source="environment.get_name_display", read_only=True, allow_null=True)
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    test_case_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    test_cases = TestCaseSerializer(many=True, read_only=True)
    results = serializers.SerializerMethodField()
    result_counts = serializers.SerializerMethodField()

    class Meta:
        """Prevent clients from forging lifecycle, summary, or creator fields."""

        model = TestRun
        fields = (
            "id", "project_id", "project_name", "environment_id", "environment_name", "name", "mode",
            "mode_label", "status", "status_label", "test_case_ids", "test_cases", "results", "result_counts",
            "execution_config", "summary", "started_at", "completed_at", "created_by", "created_at",
        )
        read_only_fields = (
            "id", "project_name", "environment_name", "mode_label", "status", "status_label", "test_cases",
            "results", "result_counts", "summary", "started_at", "completed_at", "created_by", "created_at",
        )
        extra_kwargs = {"execution_config": {"required": False}}
        validators = []

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate project ownership for environment and selected cases."""
        project = attrs.get("project")
        if project is None and self.instance:
            project = self.instance.project
        environment = attrs.get("environment", serializers.empty)
        if environment is not serializers.empty and environment is not None and environment.project_id != project.pk:
            raise serializers.ValidationError({"environment_id": "执行环境必须属于同一个项目。"})
        case_ids = self.initial_data.get("test_case_ids", serializers.empty)
        if case_ids is serializers.empty and self.instance:
            return attrs
        case_ids = [] if case_ids is serializers.empty else case_ids
        if not isinstance(case_ids, list):
            raise serializers.ValidationError({"test_case_ids": "测试用例必须是 ID 数组。"})
        cases = list(TestCase.objects.filter(id__in=case_ids, project=project))
        if len(cases) != len(set(str(item) for item in case_ids)):
            raise serializers.ValidationError({"test_case_ids": "只能选择当前项目中存在的测试用例。"})
        attrs["_test_cases"] = cases
        attrs.pop("test_case_ids", None)
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TestRun:
        """Persist a pending run and attach validated cases atomically at the view boundary."""
        cases = validated_data.pop("_test_cases", [])
        return create_test_run(
            project=validated_data.pop("project"),
            user=self.context["request"].user,
            name=validated_data.pop("name"),
            mode=validated_data.pop("mode", TestRun.Mode.IMMEDIATE),
            environment=validated_data.pop("environment", None),
            cases=cases,
            execution_config=validated_data.pop("execution_config", {}),
        )

    def update(self, instance: TestRun, validated_data: dict[str, Any]) -> TestRun:
        """Allow only pending-run selection edits; lifecycle remains service-owned."""
        cases = validated_data.pop("_test_cases", None)
        validated_data.pop("project", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if cases is not None:
            instance.test_cases.set(cases)
        return instance

    def get_results(self, obj: TestRun) -> list[dict[str, Any]]:
        """Return bounded safe results for the run detail and list views."""
        return TestResultSerializer(obj.results.select_related("test_case").all()[:200], many=True).data

    def get_result_counts(self, obj: TestRun) -> dict[str, int]:
        """Return status counts without exposing response content."""
        counts = {status: 0 for status, _ in TestResult.Status.choices}
        for row in obj.results.values("status").annotate(count=Count("id")):
            status = row["status"]
            count = row["count"]
            counts[status] = count
        return counts
