"""Concept mode creates no browser and makes no product interaction claims."""
from contracts.models import TaskOutcome, TaskResult


def run_concept_tasks(user, config, run_id) -> list[TaskResult]:
    return [TaskResult(run_id=run_id, user_id=user.user_id, task_id=task.task_id,
                       outcome=TaskOutcome.NOT_ATTEMPTED,
                       reason="concept evaluation: no product interaction")
            for task in config.tasks]
