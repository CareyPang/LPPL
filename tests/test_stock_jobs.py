import uuid

import pytest

from research.pipeline.stock_jobs import cli_job, workflow_inputs

JOB = {"job_id": "35fb2d27-e5cf-4820-bb27-c3d099540c1a",
       "requested_at": "2026-11-06T00:00:00Z", "source_sha": "a" * 40}


def test_dispatch_identity_and_separate_modes():
    current = workflow_inputs("repository_dispatch", {"code": "600519", **JOB}, "b" * 40)
    assert current["mode"] == "current" and current["weeks"] == "0"
    history = workflow_inputs("repository_dispatch", {
        "code": "600519", "mode": "history", "history_weeks": "104", **JOB
    }, "b" * 40)
    assert history["source_sha"] == JOB["source_sha"] and history["weeks"] == "104"


@pytest.mark.parametrize("overrides", [
    {"job_id": "../escape"}, {"source_sha": "main"}, {"source_sha": "a" * 40 + "\nfoo=bar"},
    {"requested_at": "2026-11-06T08:00:00+08:00"}, {"requested_at": "2026-11-06"},
    {"code": "600519\nINJECT=1"}, {"code": "６００５１９"}, {"mode": "both"},
    {"variant": "stk_full"}, {"history_weeks": "104"},
    {"mode": "history", "history_weeks": "157"},
])
def test_dispatch_rejects_unsafe_identity_and_invalid_budget(overrides):
    with pytest.raises((ValueError, TypeError)):
        workflow_inputs("repository_dispatch", {"code": "600519", **JOB, **overrides}, "b" * 40)


def test_legacy_cli_identity_is_optional_but_partial_identity_is_rejected():
    assert cli_job() == {}
    with pytest.raises(ValueError):
        cli_job(JOB["job_id"])


def test_manual_run_has_server_generated_identity_and_current_default():
    job = workflow_inputs("workflow_dispatch", {"code": "600519"}, "b" * 40)
    assert str(uuid.UUID(job["job_id"])) == job["job_id"]
    assert job["source_sha"] == "b" * 40 and job["weeks"] == "0"
