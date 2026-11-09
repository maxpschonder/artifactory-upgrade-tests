# Artifactory Upgrade Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pytest suite that pushes and pulls artifacts for 6 formats × 3 repository types before and after an Artifactory upgrade and reports the comparison.

**Architecture:** A Python runner container (`aut` package) drives pytest. Tests call format adapters that run native clients in long-lived Compose client containers via `docker exec`; files are exchanged through a shared `/work` volume. The runner writes a manifest, results JSON, JUnit XML, and a self-contained HTML report.

**Tech Stack:** Python 3.13, pytest, PyYAML, Docker Compose, skopeo, mvn, npm, pip/twine, helm, curl.

**Spec:** `SPEC.md`, design `docs/superpowers/specs/2026-11-09-artifactory-upgrade-tests-design.md`.

## Global Constraints

- Environment: `ARTIFACTORY_URL`, `ARTIFACTORY_TOKEN`; repository names per format and type in YAML (`config.yaml`).
- Entry points: `./run.sh pre`, `./run.sh post`.
- Checksums: SHA-256.
- Run ID in every generated name: `r<YYYYMMDDHHMMSS><4 hex>` (alphanumeric, valid for every format).
- Proxy: forward `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` to containers; no further handling.
- Dev Artifactory image version from `ARTIFACTORY_VERSION`.
- Tokens never appear in logs, manifests, or reports.

## Review Focus

- Missing or changed old artifacts must fail `post` even when fresh push/pull passes.
- The report must always show 18 rows, with unknown phases shown as pending.
- HTML must escape log and error text.
- Malformed config or manifest must fail before any test runs.
- Manifest retrieval must not leave the configured instance (coordinates only, no URLs).

## File Structure

| File | Responsibility |
|---|---|
| `aut/config.py` | Load and validate YAML config and environment |
| `aut/clients.py` | `docker exec` executor, redaction, SHA-256 helpers |
| `aut/formats.py` | Six adapters: build, push, pull, upstream coordinates, cache names |
| `aut/suite.py` | Operations per combination and per manifest entry |
| `aut/plugin.py` | pytest plugin: parametrization, result collection |
| `aut/store.py` | Run IDs, manifest and results persistence |
| `aut/report.py` | HTML report |
| `aut/__main__.py` | CLI: `pre`, `post`, `report` |
| `aut/setup.py` | Dev setup: token, license, repositories |
| `suite_tests/` | The pytest tests that pytest collects at run time |
| `tests/` | Unit tests with a fake adapter |
| `compose.yml`, `clients/`, `run.sh` | Runtime orchestration |
| `dev/compose.yml` | Versioned Artifactory dev stack |

## Tasks

### Task 1: Config, store, and helpers
- [x] Tests: config rejects missing formats/repo names/env vars; run ID format; manifest round trip and validation; redaction; JWT username.
- [x] Implement `config.py`, `store.py`, `clients.py`; run tests.

### Task 2: Suite operations and pytest plugin
- [x] Tests with fake adapter: local/remote/virtual pass; checksum mismatch fails; missing old artifact fails while fresh run passes; virtual without deploy target passes with an n/a note.
- [x] Implement `suite.py`, `plugin.py`, `suite_tests/`, `__main__.py`; run tests.

### Task 3: Format adapters
- [x] Tests: generated artifacts are deterministic per name; docker `dir:` layout digests match; command scripts contain no token literal.
- [x] Implement `formats.py`; run tests.

### Task 4: Report
- [x] Tests: 18 rows; pending columns; escaped error text; failed retention marks the row red.
- [x] Implement `report.py`; run tests.

### Task 5: Orchestration, dev stack, docs
- [x] `compose.yml`, Dockerfiles, `run.sh`, `dev/compose.yml`, `aut/setup.py`, `config.yaml`, `.env.example`, `README.md`.
- [x] Validate with `docker compose config` and `sh -n run.sh`.
- [ ] Run the live scenario against a licensed dev instance (not run: no Docker daemon access in the sandbox, no license).
