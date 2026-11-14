from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "stock_nightly.yml"
)


def _workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _workflow_inputs(workflow):
    return workflow.get("on", workflow.get(True, {}))["workflow_dispatch"]["inputs"]


def test_stock_nightly_retry_is_guarded_and_reuses_resolved_plan():
    workflow = _workflow()
    retry = workflow["jobs"]["retry"]
    condition = retry["if"]
    run_step = next(
        step
        for step in retry["steps"]
        if step["name"] == "Dispatch one retry with the resolved plan"
    )

    assert retry["needs"] == ["plan", "fit"]
    assert "always()" in condition
    assert "needs.plan.result == 'success'" in condition
    assert "needs.fit.result == 'failure'" in condition
    assert "github.event_name != 'pull_request'" in condition
    assert "!inputs.retry_of" in condition
    assert retry["permissions"]["actions"] == "write"
    assert retry["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert {
        "PLAN_UNIVERSE": retry["env"]["PLAN_UNIVERSE"],
        "PLAN_VARIANT": retry["env"]["PLAN_VARIANT"],
        "PLAN_SHARDS": retry["env"]["PLAN_SHARDS"],
        "PLAN_ASOF": retry["env"]["PLAN_ASOF"],
    } == {
        "PLAN_UNIVERSE": "${{ needs.plan.outputs.universe }}",
        "PLAN_VARIANT": "${{ needs.plan.outputs.variant }}",
        "PLAN_SHARDS": "${{ needs.plan.outputs.shards }}",
        "PLAN_ASOF": "${{ needs.plan.outputs.asof }}",
    }
    assert (
        'gh workflow run stock_nightly.yml --repo "$GITHUB_REPOSITORY" --ref main'
        in run_step["run"]
    )
    assert "universe=$PLAN_UNIVERSE" in run_step["run"]
    assert "variant=$PLAN_VARIANT" in run_step["run"]
    assert "shards=$PLAN_SHARDS" in run_step["run"]
    assert "asof=$PLAN_ASOF" in run_step["run"]
    assert "retry_of=$GITHUB_RUN_ID" in run_step["run"]
    assert workflow["jobs"]["publish"]["if"] == "needs.fit.result == 'success'"


def test_retry_of_input_and_planned_asof_are_preserved_in_retry():
    workflow = _workflow()
    inputs = _workflow_inputs(workflow)
    plan = workflow["jobs"]["plan"]
    plan_script = next(step["run"] for step in plan["steps"] if step.get("id") == "plan")
    summary_step = next(
        step for step in plan["steps"] if step.get("name") == "Record retry origin"
    )

    assert inputs["retry_of"]["type"] == "string"
    assert inputs["retry_of"]["default"] == ""
    assert inputs["asof"]["type"] == "string"
    assert inputs["asof"]["default"] == ""
    assert {"universe", "variant", "shards"} <= inputs.keys()
    assert 'asof="${INPUT_ASOF:-}"' in plan_script
    assert "date.fromisoformat" in plan_script
    for key in ("universe", "asof", "variant", "shards"):
        assert plan["outputs"][key] == f"${{{{ steps.plan.outputs.{key} }}}}"
    assert summary_step["env"]["RETRY_OF"] == "${{ inputs.retry_of }}"
    assert "GITHUB_STEP_SUMMARY" in summary_step["run"]
