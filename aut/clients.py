"""Running native clients in their Compose containers, plus REST calls from the runner."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import quote


class CommandError(Exception):
    pass


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_dir(path, exclude=()):
    return {p.name: sha256_file(p) for p in sorted(Path(path).iterdir())
            if p.is_file() and p.name not in exclude}


class Log:
    """Per-test log; every line is redacted before it is stored or printed."""

    def __init__(self, secrets):
        self.secrets = [s for s in secrets if s]
        self.lines = []

    def redact(self, text):
        for s in self.secrets:
            text = text.replace(s, "***")
        return text

    def add(self, text):
        text = self.redact(str(text))
        self.lines.append(text)
        print(text)

    def text(self):
        return "\n".join(self.lines)


class Shell:
    """Runs client shell scripts; all native clients live in the runner image.

    Credentials travel as environment variables, so scripts reference
    $ARTIFACTORY_TOKEN instead of embedding the value. The service name
    only labels the log.
    """

    def __init__(self, config, timeout=900):
        self.timeout = timeout
        self.env = {
            "ARTIFACTORY_TOKEN": config.token,
            "ARTIFACTORY_USER": config.user,
            "AUT_USER_Q": quote(config.user, safe=""),
        }

    def __call__(self, service, script, log):
        log.add(f"$ [{service}] {script}")
        try:
            proc = subprocess.run(["sh", "-ec", script], env={**os.environ, **self.env},
                                  capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise CommandError(f"{service}: timed out after {self.timeout}s") from e
        output = (proc.stdout + proc.stderr).strip()
        if output:
            log.add(output)
        if proc.returncode:
            # Clients like mvn end with boilerplate, so prefer substantial error lines;
            # the full output is in the log.
            lines = log.redact(output).splitlines()
            errors = [line for line in lines if "error" in line.lower() and len(line.strip()) > 40][:3]
            summary = "\n".join(errors or lines[-20:])
            raise CommandError(f"{service}: exit {proc.returncode}: {summary[-3000:]}")
        return proc.stdout


class Api:
    """Minimal Artifactory REST client using the access token."""

    def __init__(self, config, timeout=60):
        self.config = config
        self.timeout = timeout

    def __call__(self, method, path, body=None, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        req = urllib.request.Request(self.config.url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.config.token}")
        if data is not None:
            req.add_header("Content-Type", content_type)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")
