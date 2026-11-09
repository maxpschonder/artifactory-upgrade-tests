"""CLI: python -m aut pre|post|report."""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import config as cfg
from . import report, store
from .plugin import SuitePlugin

SUITE_DIR = Path(__file__).resolve().parent.parent / "suite_tests"


def default_runtime(config):
    from .clients import Api, Shell
    from .formats import ADAPTERS
    return Shell(config), Api(config), ADAPTERS


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_phase(args, env, runtime=default_runtime):
    out = Path(args.out)
    try:
        config = cfg.load(args.config, env)
        old_entries, pre_dir = [], None
        if args.phase == "post":
            manifest_path = Path(args.manifest) if args.manifest else latest_pre(out) / "manifest.json"
            old_entries = store.load_manifest(manifest_path)["artifacts"]
            pre_dir = manifest_path.parent
    except (cfg.ConfigError, store.ManifestError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    run, api, adapters = runtime(config)
    run_id = store.new_run_id()
    out_dir = out / f"{args.phase}-{run_id}"
    try:
        version = api("GET", "/api/system/version")["version"]
    except Exception as e:  # recorded in the report; the tests show the real failure
        version = f"unknown ({e})"
    meta = {"phase": args.phase, "run_id": run_id, "started": now(), "url": config.url,
            "artifactory_version": version, "formats": list(config.formats), "pre_dir": str(pre_dir) if pre_dir else None}
    store.write_json(out_dir / "meta.json", meta)
    print(f"{args.phase} run {run_id} against {config.url} (Artifactory {version}), output {out_dir}")

    session = SimpleNamespace(config=config, phase=args.phase, run_id=run_id, out_dir=out_dir,
                              workdir=Path(args.workdir) / run_id, run=run, api=api,
                              adapters=adapters, old_entries=old_entries)
    plugin = SuitePlugin(session)
    files = ["matrix.py"] if args.phase == "pre" else ["retention.py", "matrix.py"]
    code = pytest.main([
        *(str(SUITE_DIR / f) for f in files),
        "-p", "no:cacheprovider", "-q", "-rfE", "--rootdir", str(SUITE_DIR),
        "-o", "junit_logging=system-out", "-o", f"junit_suite_name=artifactory-{args.phase}",
        "--junitxml", str(out_dir / "junit.xml"),
    ], plugins=[plugin])

    store.write_json(out_dir / "results.json", plugin.records)
    store.write_json(out_dir / "manifest.json", store.manifest(run_id, plugin.entries))
    store.write_json(out_dir / "meta.json", {**meta, "finished": now(), "pytest_exit": int(code)})
    if args.phase == "pre":
        (out / "latest-pre").write_text(out_dir.name + "\n")
    html_path = out_dir / "report.html"
    html_path.write_text(report.render(report.load(pre_dir or out_dir),
                                       report.load(out_dir) if pre_dir else None))
    print(f"report: {html_path}")
    return 0 if code == 0 else 1


def latest_pre(out):
    pointer = out / "latest-pre"
    if not pointer.exists():
        raise store.ManifestError(f"no pre run found in {out}; pass --manifest")
    return out / pointer.read_text().strip()


def main(argv=None, env=None):
    p = argparse.ArgumentParser(prog="aut", description="Artifactory upgrade tests")
    p.add_argument("phase", choices=["pre", "post", "report"])
    p.add_argument("--config", default=os.environ.get("AUT_CONFIG", "config.yaml"))
    p.add_argument("--out", default="out", help="output directory")
    p.add_argument("--workdir", default="/work", help="scratch directory for built and pulled artifacts")
    p.add_argument("--manifest", help="post: manifest of the pre run (default: latest pre in --out)")
    p.add_argument("--pre", help="report: pre run directory")
    p.add_argument("--post", help="report: post run directory")
    args = p.parse_args(argv)
    if args.phase == "report":
        if not args.pre:
            p.error("report needs --pre")
        target = Path(args.post or args.pre) / "report.html"
        target.write_text(report.render(report.load(Path(args.pre)),
                                        report.load(Path(args.post)) if args.post else None))
        print(f"report: {target}")
        return 0
    return run_phase(args, os.environ if env is None else env)


if __name__ == "__main__":
    sys.exit(main())
