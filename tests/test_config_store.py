import re

import pytest
import yaml

from aut import config as cfg
from aut import store
from conftest import ENV, ROOT, jwt


def write_config(tmp_path, mutate):
    data = yaml.safe_load((ROOT / "config.yaml").read_text())
    mutate(data)
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_example_config_loads(config):
    assert set(config.formats) == set(cfg.FORMATS)
    assert config.user == "admin"
    assert config.registry == "artifactory:8082"
    assert config.insecure


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["formats"].pop("helm"), "formats.helm: missing"),
    (lambda d: d["formats"]["npm"].update(local="bad key"), "formats.npm.local"),
    (lambda d: d["formats"]["maven"]["upstream"].pop("version"), "formats.maven.upstream"),
    (lambda d: d["formats"]["generic"]["upstream"].update(path="../etc/passwd"), "invalid value"),
    (lambda d: d["formats"]["docker"]["upstream"].update(reference="x; rm -rf /"), "invalid value"),
    (lambda d: d["formats"].update(conan={}), "unknown conan"),
])
def test_invalid_config_is_rejected(tmp_path, mutate, message):
    with pytest.raises(cfg.ConfigError, match=re.escape(message)):
        cfg.load(write_config(tmp_path, mutate), ENV)


def test_environment_is_required():
    with pytest.raises(cfg.ConfigError) as e:
        cfg.load(ROOT / "config.yaml", {})
    assert "ARTIFACTORY_URL" in str(e.value) and "ARTIFACTORY_TOKEN" in str(e.value)


def test_user_from_token_and_override():
    assert cfg.user_from_token(jwt("jfrt@01x/users/ci-bot")) == "ci-bot"
    assert cfg.user_from_token("not-a-jwt") is None
    with pytest.raises(cfg.ConfigError, match="ARTIFACTORY_USER"):
        cfg.load(ROOT / "config.yaml", {**ENV, "ARTIFACTORY_TOKEN": "opaque"})
    assert cfg.load(ROOT / "config.yaml", {**ENV, "ARTIFACTORY_TOKEN": "opaque", "ARTIFACTORY_USER": "u"}).user == "u"


def test_run_id_is_alphanumeric_and_unique():
    ids = {store.new_run_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(re.fullmatch(r"r\d{14}[0-9a-f]{4}", i) for i in ids)


def good_entry():
    return store.entry("npm", "local", "aut-npm-local", {"name": "x", "version": "1.0.0"}, {"x.tgz": "c" * 64})


def test_manifest_round_trip(tmp_path):
    path = tmp_path / "manifest.json"
    store.write_json(path, store.manifest("r1", [good_entry()]))
    assert store.load_manifest(path)["artifacts"] == [good_entry()]


@pytest.mark.parametrize("mutate, message", [
    (lambda e: e.update(format="conan"), "unknown format"),
    (lambda e: e.update(repo="https://evil.example/x"), "invalid repository key"),
    (lambda e: e["coords"].update(name="https://evil.example/x"), "invalid value"),
    (lambda e: e.update(checksums={"x": "nothex"}), "SHA-256"),
    (lambda e: e.update(checksums={}), "SHA-256"),
])
def test_invalid_manifest_is_rejected(tmp_path, mutate, message):
    e = good_entry()
    mutate(e)
    path = tmp_path / "manifest.json"
    store.write_json(path, store.manifest("r1", [e]))
    with pytest.raises(store.ManifestError, match=message):
        store.load_manifest(path)


def test_token_not_in_repr(config):
    assert config.token not in repr(config)
