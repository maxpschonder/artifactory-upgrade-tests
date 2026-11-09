"""Dev setup: wait for Artifactory, install a license, create a token and the test repositories.

python -m aut.setup            create what is missing, write ARTIFACTORY_TOKEN to .env
python -m aut.setup --delete   delete the configured test repositories

Repositories are changed through the YAML configuration patch API, because the
repository REST API is not available in Artifactory OSS.
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from .config import FORMATS

REMOTE_EXTRAS = {"docker": {"enableTokenAuthentication": True}}


def request(url, method="GET", body=None, auth=None, content_type="application/json"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method)
    if auth:
        req.add_header("Authorization", auth)
    if data is not None:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode()


def wait_ready(url, timeout=600):
    deadline = time.time() + timeout
    while True:
        try:
            if request(f"{url}/api/system/ping") == "OK":
                return
        except (urllib.error.URLError, OSError):
            pass
        if time.time() > deadline:
            sys.exit(f"Artifactory at {url} not ready after {timeout}s")
        print("waiting for Artifactory ...")
        time.sleep(10)


def create_token(url, admin, basic):
    """The Access API rejects Basic auth in some versions (7.146 OSS); the deprecated
    Artifactory token endpoint still accepts it and issues a token with the user's permissions."""
    try:
        return request(url.rsplit("/artifactory", 1)[0] + "/access/api/v1/tokens", "POST",
                       {"username": admin, "scope": "applied-permissions/admin", "expires_in": 30 * 86400,
                        "description": "artifactory upgrade tests"}, basic)["access_token"]
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
    form = f"username={admin}&scope=applied-permissions/user&expires_in={30 * 86400}".encode()
    return request(f"{url}/api/security/token", "POST", form, basic,
                   "application/x-www-form-urlencoded")["access_token"]


def save_token(env_file, token):
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.startswith("ARTIFACTORY_TOKEN=")] + [f"ARTIFACTORY_TOKEN={token}"]
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)


def repo_specs(fmt, section):
    """(config section, key, spec) for the format's local, remote, and virtual repository."""
    local, remote, virtual = section["local"], section["remote"], section["virtual"]
    yield "localRepositories", local, {"type": fmt}
    yield "remoteRepositories", remote, {"type": fmt, "url": section["remote_url"], **REMOTE_EXTRAS.get(fmt, {})}
    spec = {"type": fmt, "repositories": [local, remote]}
    if section.get("virtual_deploy"):
        spec["defaultDeploymentRepo"] = local
    yield "virtualRepositories", virtual, spec


def patch(url, auth, changes):
    body = yaml.safe_dump(changes).encode()
    print(request(f"{url}/api/system/configuration", "PATCH", body, auth, "application/yaml").strip())


def main(argv=None):
    p = argparse.ArgumentParser(prog="aut.setup")
    p.add_argument("--config", default=os.environ.get("AUT_CONFIG", "config.yaml"))
    p.add_argument("--env-file", default=".env")
    p.add_argument("--license", default="dev/artifactory.lic", help="license key file, installed if present")
    p.add_argument("--delete", action="store_true", help="delete the configured test repositories")
    args = p.parse_args(argv)

    url = os.environ["ARTIFACTORY_URL"].rstrip("/")
    formats = yaml.safe_load(Path(args.config).read_text())["formats"]
    wait_ready(url)

    admin = os.environ.get("ARTIFACTORY_ADMIN_USER", "admin")
    basic = "Basic " + base64.b64encode(
        f"{admin}:{os.environ.get('ARTIFACTORY_ADMIN_PASSWORD', 'password')}".encode()).decode()

    lic = Path(args.license)
    if lic.exists():
        request(f"{url}/api/system/license", "POST", {"licenseKey": lic.read_text().strip()}, basic)
        print(f"installed license from {lic}")

    token = os.environ.get("ARTIFACTORY_TOKEN")
    if not token:
        token = create_token(url, admin, basic)
        save_token(Path(args.env_file), token)
        print(f"created a 30-day token for {admin}, saved to {args.env_file}")
    bearer = f"Bearer {token}"

    enabled = [f.strip() for f in os.environ.get("AUT_FORMATS", "").split(",") if f.strip()] or FORMATS
    specs = [s for fmt in FORMATS if fmt in enabled for s in repo_specs(fmt, formats[fmt])]
    existing = {r["key"]: (r["type"].lower(), r["packageType"].lower())
                for r in request(f"{url}/api/repositories", auth=bearer)}

    if args.delete:
        # Virtual repositories first, since they reference the others.
        for section in ("virtualRepositories", "remoteRepositories", "localRepositories"):
            keys = [k for s, k, _ in specs if s == section and k in existing]
            if keys:
                patch(url, bearer, {section: {k: None for k in keys}})
                print(f"deleted {', '.join(keys)}")
        return

    changes = {}
    for section, key, spec in specs:
        rclass = section.removesuffix("Repositories")
        if key not in existing:
            changes.setdefault(section, {})[key] = spec
            print(f"creating {key}")
        elif existing[key] != (rclass, spec["type"]):
            sys.exit(f"{key} exists as {' '.join(existing[key])}, expected {rclass} {spec['type']}; not changing it")
        else:
            print(f"exists {key}")
    # Order matters: virtual repositories must reference existing members.
    for section in ("localRepositories", "remoteRepositories", "virtualRepositories"):
        if section in changes:
            patch(url, bearer, {section: changes[section]})


if __name__ == "__main__":
    main()
