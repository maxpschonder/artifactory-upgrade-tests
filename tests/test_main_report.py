import json
import re
from types import SimpleNamespace

from aut import report, store
from aut.__main__ import run_phase
from conftest import ENV, ROOT


def run(fake, tmp_path, phase, manifest=None, env=ENV):
    config = tmp_path / "config.yaml"
    config.write_text((ROOT / "config.yaml").read_text().replace("pull_retry_delay: 3", "pull_retry_delay: 0"))
    args = SimpleNamespace(phase=phase, config=str(config), out=str(tmp_path / "out"),
                           workdir=str(tmp_path / "work"), manifest=manifest)
    return run_phase(args, env, runtime=lambda config: (None, fake.api, fake.adapters))


def results(run_dir):
    return json.loads((run_dir / "results.json").read_text())


def test_pre_then_post_detects_deleted_artifact(fake, tmp_path):
    out = tmp_path / "out"
    assert run(fake, tmp_path, "pre") == 0
    pre_dir = out / (out / "latest-pre").read_text().strip()
    pre_results = results(pre_dir)
    assert len(pre_results) == 18 and all(r["status"] == "passed" for r in pre_results)
    assert (pre_dir / "junit.xml").exists()

    entries = store.load_manifest(pre_dir / "manifest.json")["artifacts"]
    victim = next(e for e in entries if e["format"] == "maven" and e["repo_type"] == "local")
    fake.delete(victim["repo"], victim["coords"])

    assert run(fake, tmp_path, "post") == 1
    post_dir = next(p for p in out.iterdir() if p.name.startswith("post-"))
    post_results = results(post_dir)
    retention = [r for r in post_results if r["kind"] == "retention"]
    assert len(retention) == len(entries)
    assert [(r["format"], r["repo_type"]) for r in retention if r["status"] == "failed"] == [("maven", "local")]
    assert all(r["status"] == "passed" for r in post_results if r["kind"] == "matrix")

    html = (post_dir / "report.html").read_text()
    assert len(re.findall(r"<tr><th>(?:docker|maven|npm|pypi|helm|generic)</th>", html)) == 18
    assert "FAIL" in html and fake.config.token not in html
    junit = (post_dir / "junit.xml").read_text()
    assert 'name="test_old_artifact[maven-local-' in junit and "<failure" in junit


def test_post_without_pre_manifest_fails_early(fake, tmp_path):
    assert run(fake, tmp_path, "post") == 2


def test_report_pending_and_escaping():
    pre = {"meta": {"run_id": "r1", "url": "http://a"}, "results": [
        {"kind": "matrix", "format": "npm", "repo_type": "local", "name": "t", "status": "failed",
         "duration": 1, "error": "<script>alert(1)</script>", "log": "a & b"}]}
    html = report.render(pre, None)
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "a &amp; b" in html
    assert len(re.findall(r"<tr><th>(?:docker|maven|npm|pypi|helm|generic)</th>", html)) == 18
    assert html.count("PENDING</span>") == 36  # both post columns for 18 rows
    assert html.count('MISSING</span></td>') == 17  # pre rows without a result


def test_format_filter_runs_subset_and_reports_disabled(fake, tmp_path):
    assert run(fake, tmp_path, "pre", env={**ENV, "AUT_FORMATS": "maven,generic"}) == 0
    out = tmp_path / "out"
    pre_dir = out / (out / "latest-pre").read_text().strip()
    assert {r["format"] for r in results(pre_dir)} == {"maven", "generic"}
    html = (pre_dir / "report.html").read_text()
    assert html.count("DISABLED</span></td>") == 12


def test_unknown_format_filter_is_rejected(fake, tmp_path):
    assert run(fake, tmp_path, "pre", env={**ENV, "AUT_FORMATS": "maven,conan"}) == 2
