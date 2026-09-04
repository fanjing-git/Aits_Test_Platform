"""Django Admin integration for projects and memberships."""

from django.contrib import admin

from apps.projects.models import Project, ProjectMember


class ProjectMemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "description", "created_by__username")
    autocomplete_fields = ("created_by",)
    inlines = (ProjectMemberInline,)


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ("project", "user", "role", "joined_at")
    list_filter = ("role", "project")
    search_fields = ("project__name", "user__username", "user__email")
    autocomplete_fields = ("project", "user")
