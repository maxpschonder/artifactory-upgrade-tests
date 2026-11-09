import dataclasses

import pytest

from aut.suite import SuiteError, run_combination, verify_entry


def test_local_push_pull_records_entry(ctx, fake):
    run_combination(ctx, fake.adapters["npm"], "local")
    [e] = ctx.entries
    assert (e["repo_type"], e["repo"]) == ("local", "aut-npm-local")


def test_remote_checks_cache(ctx, fake):
    run_combination(ctx, fake.adapters["maven"], "remote")
    assert ctx.entries[0]["coords"] == ctx.config.formats["maven"].upstream
    assert "cache evidence: aut-maven-remote-cache" in ctx.log.text()


def test_remote_without_cache_fails(ctx, fake):
    fake.api = lambda *a, **k: {"results": []}
    ctx.api = fake.api
    with pytest.raises(SuiteError, match="found in aut-maven-remote-cache"):
        run_combination(ctx, fake.adapters["maven"], "remote")


def test_virtual_pulls_local_and_remote_and_deploys(ctx, fake):
    run_combination(ctx, fake.adapters["helm"], "virtual")
    assert len(ctx.entries) == 3
    assert {e["repo"] for e in ctx.entries} == {"aut-helm-virtual"}


def test_virtual_without_deploy_target_is_na(ctx, fake):
    formats = dict(ctx.config.formats)
    formats["helm"] = dataclasses.replace(formats["helm"], virtual_deploy=False)
    ctx.config = dataclasses.replace(ctx.config, formats=formats)
    run_combination(ctx, fake.adapters["helm"], "virtual")
    assert len(ctx.entries) == 2
    assert "n/a: push via virtual skipped" in ctx.log.text()


def test_checksum_mismatch_fails(ctx, fake):
    run_combination(ctx, fake.adapters["generic"], "local")
    entry = dict(ctx.entries[0], checksums={"other.bin": "d" * 64})
    with pytest.raises(SuiteError, match="checksum mismatch"):
        verify_entry(ctx, fake.adapters["generic"], entry)


def test_missing_artifact_fails_after_retries(ctx, fake):
    run_combination(ctx, fake.adapters["generic"], "local")
    entry = ctx.entries[0]
    fake.delete(entry["repo"], entry["coords"])
    with pytest.raises(SuiteError, match="pull from aut-generic-local failed"):
        verify_entry(ctx, fake.adapters["generic"], entry)
    assert ctx.log.text().count("pull attempt") == ctx.config.pull_retries
