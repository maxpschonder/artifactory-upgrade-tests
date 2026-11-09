import dataclasses
import json
from pathlib import Path

import pytest

from aut.clients import Log, sha256_dir, sha256_file
from aut.formats import ADAPTERS


class Recorder:
    def __init__(self):
        self.scripts = []

    def __call__(self, service, script, log):
        self.scripts.append((service, script))
        if script.startswith("helm package"):  # emulate the chart archive helm would write
            out = script.split(" -d ")[1].strip("'")
            name = script.split()[2].strip("'").rsplit("/", 1)[1]
            (Path(out) / f"{name}-1.0.0.tgz").write_bytes(b"chart")
        return ""


@pytest.fixture
def rec(ctx):
    ctx.run = Recorder()
    return ctx.run


@pytest.mark.parametrize("fmt", ["generic", "maven", "npm", "pypi", "docker"])
def test_build_is_deterministic(ctx, fmt):
    a, b = ADAPTERS[fmt].build(ctx, "aut-r1-local"), ADAPTERS[fmt].build(ctx, "aut-r1-local")
    assert a.checksums == b.checksums and a.coords == b.coords


def test_docker_image_layout_is_consistent(ctx):
    art = ADAPTERS["docker"].build(ctx, "aut-r1-local")
    manifest = json.loads((art.path / "manifest.json").read_text())
    for desc in [manifest["config"], *manifest["layers"]]:
        blob = art.path / desc["digest"].removeprefix("sha256:")
        assert sha256_file(blob) == desc["digest"].removeprefix("sha256:")
        assert blob.stat().st_size == desc["size"]
    assert set(art.checksums) == set(sha256_dir(art.path, exclude={"version"})) | {"manifest.raw"}


@pytest.mark.parametrize("fmt", list(ADAPTERS))
def test_scripts_never_contain_the_token(ctx, rec, fmt):
    adapter = ADAPTERS[fmt]
    art = adapter.build(ctx, "aut-r1-local")
    adapter.push(ctx, "aut-x-local", art)
    try:
        adapter.pull(ctx, "aut-x-local", art.coords)
    except (KeyError, FileNotFoundError):
        pass  # nothing was downloaded by the recorder
    assert rec.scripts
    for path in ctx.workdir.rglob("*"):
        if path.is_file():
            assert ctx.config.token.encode() not in path.read_bytes()
    assert not any(ctx.config.token in s for _, s in rec.scripts)


def test_log_redacts_token():
    log = Log(["secret-token"])
    log.add("Authorization: Bearer secret-token")
    assert log.text() == "Authorization: Bearer ***"


def test_docker_uses_configured_registry(ctx, rec):
    ctx.config = dataclasses.replace(ctx.config, docker_registries={"aut-docker-local": "docker.example.com:5001"})
    adapter = ADAPTERS["docker"]
    art = adapter.build(ctx, "aut-r1-local")
    adapter.push(ctx, "aut-docker-local", art)
    assert "docker://docker.example.com:5001/aut-r1-local:1.0.0" in rec.scripts[-1][1]
