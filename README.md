# Artifactory Upgrade Tests

This suite checks an Artifactory instance before and after an upgrade. For Docker, Maven, npm, PyPI, Helm, and Generic, it pushes and pulls through Local, Remote, and Virtual repositories with each format's native client, then compares SHA-256 checksums. The `post` phase also downloads every artifact recorded by `pre` and fails if any is missing or changed.

## Requirements

You need Docker with Compose v2.13 or later. The suite runs entirely in containers: a Python/pytest runner and one client container each for skopeo, mvn, npm, pip/twine, helm, and curl. The runner controls the clients through the mounted Docker socket.

A full run needs an instance that supports all six formats, which means Artifactory Pro or a trial license. JFrog Container Registry lacks Maven, npm, and PyPI, and Artifactory OSS lacks Docker, npm, PyPI, and Helm. To test a subset, set `AUT_FORMATS`, for example `AUT_FORMATS=maven,generic` for OSS. The report then marks the other formats as DISABLED.

## Running against an existing instance

1. Copy `.env.example` to `.env`, then set `ARTIFACTORY_URL` (for example `https://artifactory.example.com/artifactory`) and `ARTIFACTORY_TOKEN`. The suite derives the user name from the token; set `ARTIFACTORY_USER` if the token subject has no `/users/<name>` part.
2. In `config.yaml`, set the repository names for each format and type. Each Virtual repository must contain the Local and Remote repository of its format. Set `virtual_deploy: true` only where the Virtual repository has a default deployment repository. The `upstream` entries name fixed public artifacts for the Remote and Virtual tests.
3. Before the upgrade, run `./run.sh pre`.
4. After the upgrade, run `./run.sh post`. By default it verifies the manifest of the latest `pre` run; pass `--manifest out/pre-<run-id>/manifest.json` to pick another.

Both phases exit with a nonzero status if any check fails. Each run writes to `out/<phase>-<run-id>/`:

| File | Content |
|---|---|
| `report.html` | Standalone report: 18 rows (format × repository type) with columns for pre, old artifacts, and post; logs expand per test |
| `junit.xml` | One test case per combination and per old artifact, for GitLab |
| `results.json` | Status, error, and redacted log per test |
| `manifest.json` | Every verified artifact: repository, coordinates, SHA-256 |
| `meta.json` | Run ID, Artifactory version, timestamps |

To rebuild a report, run `./run.sh report --pre out/pre-<id> --post out/post-<id>`.

Every generated artifact name contains the run ID (`aut-r<timestamp><hex>-local`, `-virtual`, `-vdeploy`), so repeated runs do not collide. Docker pushes go to the registry at the host of `ARTIFACTORY_URL` using the repository path method (`host/<repo>/<image>:<tag>`).

## Local upgrade scenario

The dev stack in `dev/compose.yml` runs Artifactory with PostgreSQL, because current versions refuse to start on the embedded Derby database. Both keep their data in named volumes, so recreating the Artifactory container with a newer tag performs an upgrade. `ARTIFACTORY_EDITION` selects `pro` (default, needs a license) or `oss`.

With OSS, which has been tested from 7.146.39 to 7.161.26:

```sh
cp .env.example .env
echo AUT_FORMATS=maven,generic >> .env
export ARTIFACTORY_EDITION=oss
ARTIFACTORY_VERSION=7.146.39 docker compose -f dev/compose.yml up -d --wait
./run.sh setup        # waits, creates a token in .env and the repositories
./run.sh pre
ARTIFACTORY_VERSION=7.161.26 docker compose -f dev/compose.yml up -d --wait   # upgrade, same volumes
./run.sh post
```

With Pro, put the license key in `dev/artifactory.lic` (setup installs it), leave `AUT_FORMATS` unset, and pick tags from `releases-docker.jfrog.io/jfrog/artifactory-pro`.

Setup creates repositories through the YAML configuration patch API (`PATCH /api/system/configuration`), because OSS lacks the repository REST API. If the Access API rejects Basic authentication, setup falls back to the deprecated `/api/security/token` endpoint, as 7.146 OSS requires.

To check that `post` detects a lost artifact, delete one recorded in the pre manifest before running `post`. Take the run ID from `out/latest-pre`:

```sh
curl -u admin:password -X DELETE \
  "http://localhost:8082/artifactory/aut-maven-local/aut/upgrade/aut-<run-id>-local"
./run.sh post         # maven/local shows FAIL under "Post: old artifacts"
```

`./run.sh setup --delete` removes the configured test repositories. To remove the dev instance and its data, run `docker compose -f dev/compose.yml down -v`. To remove the client containers and the shared work volume, run `docker compose down -v`.

## Development

The unit tests use an in-memory Artifactory and need only Python with pytest and PyYAML:

```sh
python -m pytest
```

| Path | Responsibility |
|---|---|
| `aut/config.py` | Load and validate `config.yaml` and the environment |
| `aut/formats.py` | Format adapters: build, push, and pull with the native client |
| `aut/suite.py` | Checks per combination and per old artifact |
| `aut/plugin.py`, `suite_tests/` | pytest parametrization and result capture |
| `aut/report.py` | HTML report |
| `aut/setup.py` | Dev token, license, and repository setup |

## Known limitations

- Proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`) are forwarded to the containers but not configured per client yet. Maven, for example, ignores them.
- Maven downloads its deploy and dependency plugins from Maven Central; only the artifacts under test go through Artifactory. For `http://` URLs the generated Maven settings lift Maven's plain-HTTP block.
- Docker, npm, PyPI, and Helm have not run against a live instance yet, because that needs a Pro or trial license.
- Remote-cache checks query AQL, which needs a token with read access to the `<remote>-cache` repositories.
- The runner needs the Docker socket. A GitLab pipeline needs a runner with Docker access (for example, Docker-in-Docker).
