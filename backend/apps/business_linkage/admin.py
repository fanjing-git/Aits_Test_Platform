"""Django Admin registration for business linkage records."""

from django.contrib import admin

from apps.business_linkage.models import BusinessLinkage


@admin.register(BusinessLinkage)
class BusinessLinkageAdmin(admin.ModelAdmin):
    """Expose linkage metadata while keeping future execution separate."""

    list_display = ("name", "project", "created_at")
    search_fields = ("name", "project__name")
    autocomplete_fields = ("project",)
