"""Admin registrations for test execution records."""

from django.contrib import admin

from apps.tests.models import Evaluation, TestCase, TestResult, TestRun


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    """Expose searchable test cases."""

    list_display = ("case_id", "title", "project", "case_type", "priority", "is_automation")
    list_filter = ("case_type", "priority", "is_automation")
    search_fields = ("case_id", "title", "project__name")


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    """Expose execution lifecycle records."""

    list_display = ("name", "project", "mode", "status", "created_at")
    list_filter = ("mode", "status")
    search_fields = ("name", "project__name")


@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    """Expose result status and case lookups."""

    list_display = ("run", "test_case", "status", "status_code", "duration_ms")
    list_filter = ("status",)
    search_fields = ("run__name", "test_case__case_id")


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    """Expose evaluation records."""

    list_display = ("run", "result", "evaluator", "score", "grade", "created_at")
    list_filter = ("evaluator", "grade")
    search_fields = ("run__name", "summary")
