"""Push/pull operations per format x repository type, and retention checks."""
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import store


class SuiteError(Exception):
    pass


@dataclass
class Ctx:
    config: object
    run_id: str
    workdir: Path
    run: object  # (service, script, log) -> stdout
    api: object  # (method, path, body=None, content_type=...) -> parsed response
    log: object
    sleep: object = time.sleep
    entries: list = field(default_factory=list)
    _counter: itertools.count = field(default_factory=itertools.count)

    def tmp(self, label):
        path = Path(self.workdir) / f"{next(self._counter):03d}-{label}"
        path.mkdir(parents=True)
        return path


def diff(expected, actual):
    lines = []
    for name in sorted(set(expected) | set(actual)):
        if expected.get(name) != actual.get(name):
            lines.append(f"  {name}: expected {expected.get(name, 'absent')}, got {actual.get(name, 'absent')}")
    return "\n".join(lines)


def pull_verified(ctx, adapter, repo, coords, expected=None):
    """Pull with a fresh client cache; retry because indexes update asynchronously."""
    attempts = max(1, ctx.config.pull_retries)
    for attempt in range(1, attempts + 1):
        try:
            sums = adapter.pull(ctx, repo, coords)
            break
        except Exception as e:
            ctx.log.add(f"pull attempt {attempt}/{attempts} from {repo} failed: {e}")
            if attempt == attempts:
                raise SuiteError(f"pull from {repo} failed: {e}") from e
            ctx.sleep(ctx.config.pull_retry_delay)
    if expected is not None and sums != expected:
        raise SuiteError(f"checksum mismatch pulling from {repo}:\n{diff(expected, sums)}")
    ctx.log.add(f"verified {repo} {coords}: " + ", ".join(f"{k}={v[:12]}" for k, v in sorted(sums.items())))
    return sums


def record(ctx, adapter, repo_type, repo, coords, sums):
    ctx.entries.append(store.entry(adapter.name, repo_type, repo, coords, sums))


def check_cached(ctx, adapter, remote, coords, sums):
    """The remote repo's cache must hold at least one of the fetched files."""
    names = adapter.cache_names(sums, coords)
    query = 'items.find(%s).include("repo","path","name")' % json.dumps(
        {"repo": f"{remote}-cache", "$or": [{"name": n} for n in names]})
    results = ctx.api("POST", "/api/search/aql", query, "text/plain").get("results", [])
    if not results:
        raise SuiteError(f"none of {names} found in {remote}-cache")
    ctx.log.add("cache evidence: " + ", ".join(f"{r['repo']}/{r['path']}/{r['name']}" for r in results))


def push_and_pull(ctx, adapter, name, push_repo, pull_repo, repo_type):
    art = adapter.build(ctx, name)
    adapter.push(ctx, push_repo, art)
    ctx.log.add(f"pushed {art.coords} to {push_repo}")
    pull_verified(ctx, adapter, pull_repo, art.coords, art.checksums)
    record(ctx, adapter, repo_type, pull_repo, art.coords, art.checksums)


def run_combination(ctx, adapter, repo_type):
    fc = ctx.config.formats[adapter.name]
    prefix = f"aut-{ctx.run_id}"
    if repo_type == "local":
        push_and_pull(ctx, adapter, f"{prefix}-local", fc.local, fc.local, "local")
    elif repo_type == "remote":
        coords = fc.upstream
        first = pull_verified(ctx, adapter, fc.remote, coords)
        pull_verified(ctx, adapter, fc.remote, coords, first)
        check_cached(ctx, adapter, fc.remote, coords, first)
        record(ctx, adapter, "remote", fc.remote, coords, first)
    elif repo_type == "virtual":
        push_and_pull(ctx, adapter, f"{prefix}-virtual", fc.local, fc.virtual, "virtual")
        sums = pull_verified(ctx, adapter, fc.virtual, fc.upstream)
        record(ctx, adapter, "virtual", fc.virtual, fc.upstream, sums)
        if fc.virtual_deploy:
            push_and_pull(ctx, adapter, f"{prefix}-vdeploy", fc.virtual, fc.virtual, "virtual")
        else:
            ctx.log.add("n/a: push via virtual skipped (virtual_deploy: false)")
    else:
        raise ValueError(repo_type)


def verify_entry(ctx, adapter, entry):
    pull_verified(ctx, adapter, entry["repo"], entry["coords"], entry["checksums"])
