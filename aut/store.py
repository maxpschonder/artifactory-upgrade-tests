"""Run IDs and JSON persistence for manifests, results, and run metadata."""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .config import FORMATS, REPO_KEY, REPO_TYPES, coord_problems

MANIFEST_VERSION = 1
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(Exception):
    pass


def new_run_id(now=None):
    """Alphanumeric only, so it is valid in every format's names and versions."""
    now = now or datetime.now(timezone.utc)
    return "r" + now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def read_json(path):
    return json.loads(Path(path).read_text())


def entry(fmt, repo_type, repo, coords, checksums):
    return {"format": fmt, "repo_type": repo_type, "repo": repo,
            "coords": dict(coords), "checksums": dict(checksums)}


def manifest(run_id, entries):
    return {"version": MANIFEST_VERSION, "run_id": run_id, "artifacts": list(entries)}


def load_manifest(path):
    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        raise ManifestError(f"cannot read manifest {path}: {e}") from e
    problems = []
    if data.get("version") != MANIFEST_VERSION:
        problems.append(f"unsupported manifest version {data.get('version')!r}")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        problems.append("artifacts: must be a list")
        artifacts = []
    for i, a in enumerate(artifacts):
        where = f"artifacts[{i}]"
        if not isinstance(a, dict) or a.get("format") not in FORMATS or a.get("repo_type") not in REPO_TYPES:
            problems.append(f"{where}: unknown format or repo_type")
            continue
        if not REPO_KEY.match(str(a.get("repo", ""))):
            problems.append(f"{where}.repo: invalid repository key")
        problems += coord_problems(a["format"], a.get("coords"), f"{where}.coords")
        sums = a.get("checksums")
        if not isinstance(sums, dict) or not sums or not all(
                isinstance(v, str) and SHA256.match(v) for v in sums.values()):
            problems.append(f"{where}.checksums: expected non-empty SHA-256 map")
    if problems:
        raise ManifestError("\n".join(problems))
    return data

