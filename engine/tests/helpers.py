import json

from contracts import db
from contracts.models import RatingDimension, RunConfig, TaskSpec
from engine.personas import generate_users


def config_for(audience, count=1, **updates):
    values = dict(product_name="Fixture", product_version="1", mode="concept",
                  concept_material="A reusable bottle refill concept", value_proposition="Reuse bottles",
                  objective="Check the engine", audience=audience, user_count=count,
                  max_concurrency=1, tasks=[TaskSpec(task_id="T1", instruction="Review concept",
                                                       success_check="text_visible:Welcome")])
    values.update(updates)
    return RunConfig(**values)


def save_fixture(conn, config, run_id="fixture"):
    db.save_run(conn, run_id, config)
    users = generate_users(run_id, config.audience, config.user_count, config.seed)
    db.save_users(conn, users)
    return users


def evaluation_response(system, user, **kwargs):
    shape = json.loads(user.split("JSON shape: ", 1)[1].split("\nProblems use", 1)[0])
    shape["ratings"] = {d.value: {"score": 4} for d in RatingDimension}
    shape["rating_reasons"] = "Authored mock response for engine tests, not product evidence."
    return shape, {"input_tokens": 10, "output_tokens": 5, "seconds": 0.01}
