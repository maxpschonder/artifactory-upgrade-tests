"""Suite configuration: repository names from YAML, credentials from the environment."""
import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

FORMATS = ("docker", "maven", "npm", "pypi", "helm", "generic")
REPO_TYPES = ("local", "remote", "virtual")
# Coordinate keys per format; used for upstream config and manifest entries alike.
COORD_KEYS = {
    "docker": ("image", "reference"),
    "maven": ("group", "artifact", "version"),
    "npm": ("name", "version"),
    "pypi": ("name", "version"),
    "helm": ("chart", "version"),
    "generic": ("path",),
}
REPO_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COORD_VALUE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@:+-]*$")
REGISTRY = re.compile(r"^[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._-]+)*$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class FormatConfig:
    local: str
    remote: str
    virtual: str
    virtual_deploy: bool
    upstream: dict

    def repo(self, repo_type):
        return getattr(self, repo_type)


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)  # keeps the token out of pytest tracebacks
    user: str
    formats: dict
    pull_retries: int = 5
    pull_retry_delay: float = 3.0
    docker_registries: dict = field(default_factory=dict)

    def docker_prefix(self, repo):
        """Image name prefix for a Docker repo. Default: the repository path method on the
        host of ARTIFACTORY_URL; formats.docker.registries overrides it per repo, e.g. for
        the port method (host:5001) or subdomains (repo.host)."""
        return self.docker_registries.get(repo) or f"{urlparse(self.url).netloc}/{repo}"

    @property
    def insecure(self):
        return self.url.startswith("http://")


def coord_problems(fmt, coords, where):
    problems = []
    if not isinstance(coords, dict) or set(coords) != set(COORD_KEYS[fmt]):
        return [f"{where}: expected keys {', '.join(COORD_KEYS[fmt])}"]
    for key, value in coords.items():
        if not isinstance(value, str) or not COORD_VALUE.match(value) or ".." in value or "://" in value:
            problems.append(f"{where}.{key}: invalid value {value!r}")
    return problems


def user_from_token(token):
    """Artifactory access tokens are JWTs whose subject ends in /users/<name>."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        sub = claims["sub"]
    except (IndexError, ValueError, KeyError, TypeError):
        return None
    return sub.rsplit("/users/", 1)[1] if "/users/" in sub else None


def load(path, env):
    problems = []
    url = env.get("ARTIFACTORY_URL", "").rstrip("/")
    token = env.get("ARTIFACTORY_TOKEN", "")
    if not re.match(r"^https?://[^/]+", url):
        problems.append("ARTIFACTORY_URL must be set to http(s)://host[:port]/artifactory")
    if not token:
        problems.append("ARTIFACTORY_TOKEN must be set")
    user = env.get("ARTIFACTORY_USER") or user_from_token(token)
    if token and not user:
        problems.append("ARTIFACTORY_USER must be set (token subject has no user)")

    try:
        raw = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e

    enabled = [f.strip() for f in env.get("AUT_FORMATS", "").split(",") if f.strip()] or list(FORMATS)
    bad = set(enabled) - set(FORMATS)
    if bad:
        problems.append(f"AUT_FORMATS: unknown {', '.join(sorted(bad))}")

    formats = {}
    raw_formats = raw.get("formats") or {}
    for fmt in (f for f in FORMATS if f in enabled):
        section = raw_formats.get(fmt)
        if not isinstance(section, dict):
            problems.append(f"formats.{fmt}: missing")
            continue
        for repo_type in REPO_TYPES:
            if not REPO_KEY.match(str(section.get(repo_type, ""))):
                problems.append(f"formats.{fmt}.{repo_type}: missing or invalid repository key")
        if not isinstance(section.get("virtual_deploy", False), bool):
            problems.append(f"formats.{fmt}.virtual_deploy: must be true or false")
        upstream = section.get("upstream")
        problems += coord_problems(fmt, upstream, f"formats.{fmt}.upstream")
        if not problems:
            formats[fmt] = FormatConfig(
                local=section["local"],
                remote=section["remote"],
                virtual=section["virtual"],
                virtual_deploy=section.get("virtual_deploy", False),
                upstream=dict(upstream),
            )
    registries = (raw_formats.get("docker") or {}).get("registries") or {}
    if not isinstance(registries, dict) or not all(
            REPO_KEY.match(str(k)) and REGISTRY.match(str(v)) for k, v in registries.items()):
        problems.append("formats.docker.registries: expected repo key -> host[:port][/path]")
    unknown = set(raw_formats) - set(FORMATS)
    if unknown:
        problems.append(f"formats: unknown {', '.join(sorted(unknown))}")
    if problems:
        raise ConfigError("\n".join(problems))
    return Config(
        url=url,
        token=token,
        user=user,
        formats=formats,
        pull_retries=int(raw.get("pull_retries", 5)),
        pull_retry_delay=float(raw.get("pull_retry_delay", 3)),
        docker_registries=dict(registries),
    )
