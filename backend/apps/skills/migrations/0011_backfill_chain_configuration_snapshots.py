"""Backfill configuration snapshots for records created before snapshot support."""

from django.db import migrations


def backfill_configuration_snapshots(apps, schema_editor):
    """Preserve the chain contract referenced by each existing layer record."""
    configuration_model = apps.get_model("skills", "SkillChainConfiguration")
    database = schema_editor.connection.alias
    configurations = configuration_model.objects.using(database).select_related("chain")
    for configuration in configurations.iterator():
        if configuration.configuration_snapshot:
            continue
        chain = configuration.chain
        configuration.configuration_snapshot = {
            "snapshot_schema_version": "skill-chain-configuration-v1",
            "layer": configuration.layer,
            "project_id": str(configuration.project_id) if configuration.project_id else None,
            "feature_key": configuration.feature_key or "",
            "request_key": configuration.request_key or "",
            "version_lock": configuration.version_lock or "",
            "overrides": configuration.overrides or {},
            "chain": {
                "id": str(chain.pk),
                "name": chain.name,
                "version": chain.version,
                "schema_version": chain.schema_version,
                "definition": chain.definition,
            },
        }
        configuration.save(using=database, update_fields=("configuration_snapshot",))


class Migration(migrations.Migration):
    """Backfill preexisting T167 configuration declarations."""

    dependencies = [("skills", "0010_configuration_snapshot")]

    operations = [
        migrations.RunPython(
            backfill_configuration_snapshots,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
