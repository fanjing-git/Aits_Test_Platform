"""T051 model and project-isolation boundary tests."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_linkage.models import BusinessLinkage
from apps.projects.models import Project


class BusinessLinkageModelTests(TestCase):
    """Verify the T051 persistence contract without implementing execution."""

    def setUp(self) -> None:
        """Create one project boundary for linkage records."""
        self.owner = get_user_model().objects.create_user(username="linkage-owner")
        self.project = Project.objects.create(
            name="Business linkage project",
            created_by=self.owner,
        )

    def test_defaults_and_project_relationship(self) -> None:
        """Create an empty linkage and preserve the architecture defaults."""
        linkage = BusinessLinkage.objects.create(
            project=self.project,
            name="Checkout flow",
        )

        self.assertEqual(linkage.steps, [])
        self.assertEqual(linkage.dependencies, [])
        self.assertEqual(linkage.test_case_ids, [])
        self.assertEqual(str(linkage), "Business linkage project / Checkout flow")
        self.assertEqual(list(self.project.business_linkages.all()), [linkage])

    def test_json_collections_have_stable_shapes(self) -> None:
        """Reject object-shaped collections and invalid case references."""
        invalid_values = (
            {"steps": {}, "dependencies": [], "test_case_ids": []},
            {"steps": [], "dependencies": {}, "test_case_ids": []},
            {"steps": [], "dependencies": [], "test_case_ids": ["case-1", "case-1"]},
            {"steps": [], "dependencies": [], "test_case_ids": ["case-1", 2]},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                linkage = BusinessLinkage(project=self.project, name="Invalid", **values)
                with self.assertRaises(ValidationError):
                    linkage.full_clean()

    def test_project_delete_cascades_linkages(self) -> None:
        """Remove project-owned linkage records with their project."""
        linkage = BusinessLinkage.objects.create(project=self.project, name="Delete me")
        linkage_id = linkage.pk

        self.project.delete()

        self.assertFalse(BusinessLinkage.objects.filter(pk=linkage_id).exists())
