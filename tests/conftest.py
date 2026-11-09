import base64
import json
from pathlib import Path

import pytest

from aut import config as cfg
from aut.clients import Log
from aut.suite import Ctx

ROOT = Path(__file__).resolve().parent.parent


def jwt(sub):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc({'sub': sub})}.sig"


TOKEN = jwt("jfac@01abc/users/admin")
ENV = {"ARTIFACTORY_URL": "http://artifactory:8082/artifactory", "ARTIFACTORY_TOKEN": TOKEN}


@pytest.fixture
def config():
    return cfg.load(ROOT / "config.yaml", ENV)


class FakeArtifactory:
    """In-memory repositories: virtual repos resolve local then remote; remotes fill a cache."""

    def __init__(self, config):
        self.config = config
        self.repos = {}  # repo -> {coords key: checksums}
        self.cache = set()

    def key(self, coords):
        return tuple(sorted(coords.items()))

    def fc_for(self, repo):
        for fmt, fc in self.config.formats.items():
            if repo in (fc.local, fc.remote, fc.virtual):
                return fmt, fc
        raise KeyError(repo)

    def push(self, repo, coords, sums):
        _, fc = self.fc_for(repo)
        if repo == fc.virtual:
            repo = fc.local
        self.repos.setdefault(repo, {})[self.key(coords)] = dict(sums)

    def pull(self, repo, coords):
        fmt, fc = self.fc_for(repo)
        members = [fc.local, fc.remote] if repo == fc.virtual else [repo]
        for member in members:
            if member == fc.remote and coords == fc.upstream:
                name = f"{fmt}-upstream.bin"
                self.cache.add((f"{member}-cache", name))
                return {name: "a" * 64}
            found = self.repos.get(member, {}).get(self.key(coords))
            if found:
                return dict(found)
        raise FileNotFoundError(f"{coords} not in {repo}")

    def delete(self, repo, coords):
        del self.repos[repo][self.key(coords)]

    def api(self, method, path, body=None, content_type=None):
        if path == "/api/system/version":
            return {"version": "7.0.0-fake"}
        query = json.loads(body[body.index("(") + 1:body.index(").include")])
        names = {o["name"] for o in query["$or"]}
        return {"results": [{"repo": r, "path": ".", "name": n} for r, n in self.cache
                            if r == query["repo"] and n in names]}


class FakeAdapter:
    def __init__(self, name, art):
        self.name = name
        self.art = art

    def build(self, ctx, name):
        from aut.formats import Artifact
        return Artifact({k: name for k in cfg.COORD_KEYS[self.name]}, {f"{name}.bin": "b" * 64}, None)

    def push(self, ctx, repo, art):
        self.art.push(repo, art.coords, art.checksums)

    def pull(self, ctx, repo, coords):
        return self.art.pull(repo, coords)

    def cache_names(self, sums, coords):
        return sorted(sums)


@pytest.fixture
def fake(config):
    art = FakeArtifactory(config)
    art.adapters = {f: FakeAdapter(f, art) for f in cfg.FORMATS}
    return art


@pytest.fixture
def ctx(config, fake, tmp_path):
    return Ctx(config=config, run_id="r1", workdir=tmp_path, run=None, api=fake.api,
               log=Log([config.token]), sleep=lambda s: None)
