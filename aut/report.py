"""Self-contained HTML report: format x repo type matrix for pre, old artifacts, and post."""
from html import escape
from pathlib import Path

from . import store
from .config import FORMATS, REPO_TYPES

LABELS = {"pass": "PASS", "fail": "FAIL", "pending": "PENDING", "none": "NONE", "missing": "MISSING", "disabled": "DISABLED"}

CSS = """
body{font-family:system-ui,sans-serif;margin:2rem;color:#1f2328}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #d0d7de;padding:.4rem .6rem;vertical-align:top;text-align:left}
th{background:#f6f8fa}.st{font-weight:600;padding:.1rem .4rem;border-radius:4px}
.pass{background:#dafbe1;color:#116329}.fail,.missing{background:#ffebe9;color:#a40e26}
.pending,.none,.disabled{background:#eaeef2;color:#57606a}
pre{white-space:pre-wrap;background:#f6f8fa;padding:.5rem;max-height:30rem;overflow:auto;font-size:.8rem}
details summary{cursor:pointer}.meta td{border:none;padding:.1rem .6rem}
"""


def load(run_dir):
    run_dir = Path(run_dir)
    if not (run_dir / "meta.json").exists():
        return None
    results = run_dir / "results.json"
    return {"meta": store.read_json(run_dir / "meta.json"),
            "results": store.read_json(results) if results.exists() else []}


def status(records, phase_ran, empty):
    if not phase_ran:
        return "pending"
    if phase_ran == "disabled" and not records:
        return "disabled"
    if not records:
        return empty
    return "fail" if any(r["status"] != "passed" for r in records) else "pass"


def cell(records, phase_ran, empty):
    st = status(records, phase_ran, empty)
    label = f'<span class="st {st}">{LABELS[st]}</span>'
    if not records:
        return f"<td>{label}</td>"
    body = "".join(
        f"<p><b>{escape(r['name'])}</b> {escape(r['status'])} in {r['duration']}s</p>"
        + (f"<pre>{escape(r['error'])}</pre>" if r["error"] else "")
        + f"<details><summary>log</summary><pre>{escape(r['log'])}</pre></details>"
        for r in records)
    return f"<td><details{' open' if st == 'fail' else ''}><summary>{label} ({len(records)})</summary>{body}</details></td>"


def pick(phase, kind, fmt, repo_type):
    return [r for r in phase["results"] if r["kind"] == kind and r["format"] == fmt and r["repo_type"] == repo_type]


def ran(phase, fmt):
    """False if the phase has not run, "disabled" if it ran without this format."""
    if not phase:
        return False
    return True if fmt in phase["meta"].get("formats", FORMATS) else "disabled"


def meta_rows(name, phase):
    if not phase:
        return f"<tr><td>{name}</td><td colspan=3>not run</td></tr>"
    m = phase["meta"]
    return (f"<tr><td>{name}</td><td>run {escape(m['run_id'])}</td><td>Artifactory {escape(str(m.get('artifactory_version')))}</td>"
            f"<td>{escape(m.get('started', ''))} – {escape(m.get('finished', 'unfinished'))}</td></tr>")


def render(pre, post):
    rows, counts = [], {}
    for fmt in FORMATS:
        for repo_type in REPO_TYPES:
            cells = [
                (pick(pre, "matrix", fmt, repo_type) if pre else [], ran(pre, fmt), "missing"),
                (pick(post, "retention", fmt, repo_type) if post else [], ran(post, fmt), "none"),
                (pick(post, "matrix", fmt, repo_type) if post else [], ran(post, fmt), "missing"),
            ]
            for c in cells:
                counts[status(*c)] = counts.get(status(*c), 0) + 1
            rows.append(f"<tr><th>{fmt}</th><th>{repo_type}</th>" + "".join(cell(*c) for c in cells) + "</tr>")
    summary = " ".join(f'<span class="st {k}">{LABELS[k]} {v}</span>' for k, v in sorted(counts.items()))
    url = (post or pre or {}).get("meta", {}).get("url", "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Artifactory upgrade tests</title><style>{CSS}</style></head>
<body><h1>Artifactory upgrade tests</h1>
<p>{escape(url)}</p>
<table class="meta">{meta_rows("pre", pre)}{meta_rows("post", post)}</table>
<p>{summary}</p>
<table><thead><tr><th>Format</th><th>Repository</th><th>Pre: push/pull</th><th>Post: old artifacts</th><th>Post: push/pull</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p>NONE: the pre run recorded no artifacts for this combination. MISSING: the phase ran but produced no result. DISABLED: the format was excluded with AUT_FORMATS.</p>
</body></html>
"""
