"""pytest plugin: parametrizes suite tests and records per-test results and artifacts."""
import re
import time

import pytest

from . import store
from .clients import Log
from .config import FORMATS, REPO_TYPES
from .suite import Ctx


class SuitePlugin:
    def __init__(self, session):
        """session: config, phase, run_id, out_dir, workdir, run, api, adapters, old_entries."""
        self.s = session
        self.records = []
        self.entries = []

    def pytest_generate_tests(self, metafunc):
        if "combo" in metafunc.fixturenames:
            combos = [(f, t) for f in FORMATS if f in self.s.config.formats for t in REPO_TYPES]
            metafunc.parametrize("combo", combos, ids=[f"{f}-{t}" for f, t in combos])
        if "old_entry" in metafunc.fixturenames:
            entries = self.s.old_entries
            metafunc.parametrize("old_entry", entries, ids=[
                f"{e['format']}-{e['repo_type']}-{i}" for i, e in enumerate(entries)])

    @pytest.fixture
    def suite(self):
        return self.s

    @pytest.fixture
    def ctx(self, request):
        label = re.sub(r"[^A-Za-z0-9-]+", "-", request.node.name).strip("-")
        ctx = Ctx(config=self.s.config, run_id=self.s.run_id, workdir=self.s.workdir / label,
                  run=self.s.run, api=self.s.api, log=Log([self.s.config.token]))
        ctx.started = time.time()
        request.node.aut_ctx = ctx
        return ctx

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        rep = (yield).get_result()
        ctx = getattr(item, "aut_ctx", None)
        if ctx is None or not (rep.when == "call" or (rep.when == "setup" and rep.failed)):
            return
        params = item.callspec.params
        if "combo" in params:
            kind, (fmt, repo_type) = "matrix", params["combo"]
        else:
            kind, fmt, repo_type = "retention", params["old_entry"]["format"], params["old_entry"]["repo_type"]
        self.records.append({
            "kind": kind, "format": fmt, "repo_type": repo_type, "name": item.name,
            "status": rep.outcome, "duration": round(time.time() - ctx.started, 1),
            # The exception message is the finding; the log already holds the client output.
            "error": ctx.log.redact(call.excinfo.exconly() if call.excinfo else rep.longreprtext)
                     if rep.failed else "",
            "log": ctx.log.text(),
        })
        self.entries += ctx.entries
        # Save after every test so a crash keeps the artifacts verified so far.
        store.write_json(self.s.out_dir / "manifest.json", store.manifest(self.s.run_id, self.entries))
        store.write_json(self.s.out_dir / "results.json", self.records)
