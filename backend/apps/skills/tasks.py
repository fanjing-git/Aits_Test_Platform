"""Celery entry points for persisted Skill-chain execution."""

from celery import shared_task


@shared_task(bind=True, name="skills.run_chain")
def run_skill_chain(self, run_id: str) -> dict[str, str]:
    """Execute one persisted Skill-chain run and return a compact status."""
    del self
    from apps.skills.execution import SkillChainExecutionService

    run = SkillChainExecutionService().run(run_id)
    return {"run_id": str(run.pk), "status": run.status, "error_code": run.error_code}
