"""Format adapters: build a test artifact, push it, pull with a fresh client cache.

Every pull returns {file name: SHA-256} for the bytes the native client received.
Scripts run in the runner image and read credentials from $ARTIFACTORY_USER,
$AUT_USER_Q (URL-encoded user), and $ARTIFACTORY_TOKEN.
"""
import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from shlex import quote as q

from .clients import sha256_bytes, sha256_dir, sha256_file

EPOCH = (1980, 1, 1, 0, 0, 0)
MTIME = 315532800  # 1980-01-01, npm rejects earlier tar timestamps


@dataclass
class Artifact:
    coords: dict
    checksums: dict
    path: object  # file or directory the push step uploads


def targz(files):
    """Deterministic .tar.gz from {path: bytes}."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), MTIME, 0o644
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0), raw.getvalue()


def zipped(files):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name, EPOCH), data)
    return raw.getvalue()


def payload(name):
    return f"Artifactory upgrade test artifact {name}\n".encode()


class Adapter:
    name = ""

    def cache_names(self, sums):
        return sorted(sums)


class Generic(Adapter):
    name = "generic"

    def build(self, ctx, name):
        path = ctx.tmp("build") / f"{name}.txt"
        path.write_bytes(payload(name))
        return Artifact({"path": f"aut/{name}/{path.name}"}, {path.name: sha256_file(path)}, path)

    def push(self, ctx, repo, art):
        ctx.run("curl", f'curl -fsS --oauth2-bearer "$ARTIFACTORY_TOKEN" -T {q(str(art.path))} '
                        f'{q(f"{ctx.config.url}/{repo}/{art.coords["path"]}")}', ctx.log)

    def pull(self, ctx, repo, coords):
        out = ctx.tmp("pull")
        target = out / coords["path"].rsplit("/", 1)[-1]
        ctx.run("curl", f'curl -fsS --oauth2-bearer "$ARTIFACTORY_TOKEN" -o {q(str(target))} '
                        f'{q(f"{ctx.config.url}/{repo}/{coords["path"]}")}', ctx.log)
        return sha256_dir(out)


class Maven(Adapter):
    name = "maven"
    plugins = {"deploy": "org.apache.maven.plugins:maven-deploy-plugin:3.1.3",
               "dependency": "org.apache.maven.plugins:maven-dependency-plugin:3.8.1"}

    def settings(self, ctx, repo):
        """Credentials only for server id "aut"; central is disabled for dependencies so
        artifacts must come from the repository under test (plugins still come from central)."""
        path = ctx.tmp("m2") / "settings.xml"
        url = f"{ctx.config.url}/{repo}"
        off = "<releases><enabled>false</enabled></releases><snapshots><enabled>false</enabled></snapshots>"
        # Maven 3.8+ blocks plain-HTTP repositories; replacing its blocker mirror allows them.
        unblock = ("<mirrors><mirror><id>maven-default-http-blocker</id><mirrorOf>external:dummy:*</mirrorOf>"
                   "<url>http://0.0.0.0/</url><blocked>false</blocked></mirror></mirrors>"
                   if ctx.config.insecure else "")
        path.write_text(f"""<settings>{unblock}
  <servers><server><id>aut</id><username>${{env.ARTIFACTORY_USER}}</username><password>${{env.ARTIFACTORY_TOKEN}}</password></server></servers>
  <profiles><profile><id>aut</id><repositories>
    <repository><id>aut</id><url>{url}</url></repository>
    <repository><id>central</id><url>https://repo.maven.apache.org/maven2</url>{off}</repository>
  </repositories></profile></profiles>
  <activeProfiles><activeProfile>aut</activeProfile></activeProfiles>
</settings>
""")
        return path

    def build(self, ctx, name):
        coords = {"group": "aut.upgrade", "artifact": name, "version": "1.0.0"}
        path = ctx.tmp("build") / f"{name}-1.0.0.jar"
        path.write_bytes(zipped({"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\r\n\r\n",
                                 "aut.txt": payload(name)}))
        return Artifact(coords, {path.name: sha256_file(path)}, path)

    def push(self, ctx, repo, art):
        c = art.coords
        ctx.run("maven", f"mvn -B -ntp -s {q(str(self.settings(ctx, repo)))} {self.plugins['deploy']}:deploy-file "
                         f"-Dfile={q(str(art.path))} -DgroupId={q(c['group'])} -DartifactId={q(c['artifact'])} "
                         f"-Dversion={q(c['version'])} -Dpackaging=jar -DgeneratePom=true "
                         f"-DrepositoryId=aut -Durl={q(f'{ctx.config.url}/{repo}')}", ctx.log)

    def pull(self, ctx, repo, coords):
        c = coords
        gav = f"{c['group']}:{c['artifact']}:{c['version']}:jar"
        rel = f"{c['group'].replace('.', '/')}/{c['artifact']}/{c['version']}"
        jar = f"{c['artifact']}-{c['version']}.jar"
        out = ctx.tmp("pull")
        # Deleting the coordinates from the local repo gives a fresh cache while keeping plugins.
        ctx.run("maven", f"rm -rf \"$HOME\"/.m2/repository/{q(rel)} && "
                         f"mvn -B -ntp -s {q(str(self.settings(ctx, repo)))} {self.plugins['dependency']}:get "
                         f"-Dtransitive=false -Dartifact={q(gav)} && "
                         f"cp \"$HOME\"/.m2/repository/{q(rel)}/{q(jar)} {q(str(out))}/", ctx.log)
        return sha256_dir(out)


class Npm(Adapter):
    name = "npm"

    def npmrc(self, ctx, repo):
        registry = f"{ctx.config.url}/api/npm/{repo}/"
        path = ctx.tmp("npmrc") / ".npmrc"
        path.write_text(f"registry={registry}\n"
                        f"{registry.split(':', 1)[1]}:_authToken=${{ARTIFACTORY_TOKEN}}\n")
        return registry, path

    def build(self, ctx, name):
        coords = {"name": name, "version": "1.0.0"}
        pkg = json.dumps({**coords, "description": "Artifactory upgrade test", "license": "UNLICENSED"}).encode()
        data, _ = targz({"package/package.json": pkg, "package/index.js": b"module.exports = 1;\n"})
        path = ctx.tmp("build") / f"{name}-1.0.0.tgz"
        path.write_bytes(data)
        return Artifact(coords, {path.name: sha256_bytes(data)}, path)

    def push(self, ctx, repo, art):
        registry, rc = self.npmrc(ctx, repo)
        ctx.run("npm", f"npm publish {q(str(art.path))} --userconfig {q(str(rc))} --registry {q(registry)}", ctx.log)

    def pull(self, ctx, repo, coords):
        registry, rc = self.npmrc(ctx, repo)
        out = ctx.tmp("pull")
        ctx.run("npm", f"cd {q(str(out))} && npm pack {q(coords['name'] + '@' + coords['version'])} "
                       f"--userconfig {q(str(rc))} --registry {q(registry)} --cache {q(str(out))}/.cache", ctx.log)
        return {p.name: sha256_file(p) for p in out.glob("*.tgz")}


class PyPI(Adapter):
    name = "pypi"

    def build(self, ctx, name):
        dist, version = name.replace("-", "_"), "1.0.0"
        info = f"{dist}-{version}.dist-info"
        files = {
            f"{dist}/__init__.py": b"",
            f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
            f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: aut\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        }
        record = "".join(f"{n},sha256={sha256_b64(d)},{len(d)}\n" for n, d in files.items()) + f"{info}/RECORD,,\n"
        files[f"{info}/RECORD"] = record.encode()
        path = ctx.tmp("build") / f"{dist}-{version}-py3-none-any.whl"
        path.write_bytes(zipped(files))
        return Artifact({"name": name, "version": version}, {path.name: sha256_file(path)}, path)

    def push(self, ctx, repo, art):
        ctx.run("pypi", 'TWINE_USERNAME="$ARTIFACTORY_USER" TWINE_PASSWORD="$ARTIFACTORY_TOKEN" '
                        f"twine upload --non-interactive --repository-url {q(f'{ctx.config.url}/api/pypi/{repo}')} "
                        f"{q(str(art.path))}", ctx.log)

    def pull(self, ctx, repo, coords):
        scheme, rest = ctx.config.url.split("://", 1)
        host = rest.split("/", 1)[0].split(":")[0]
        index = f'{scheme}://"$AUT_USER_Q:$ARTIFACTORY_TOKEN"@{q(f"{rest}/api/pypi/{repo}/simple")}'
        out = ctx.tmp("pull")
        ctx.run("pypi", f"pip download --no-deps --no-cache-dir --disable-pip-version-check --only-binary=:all: "
                        f"--trusted-host {q(host)} --index-url {index} -d {q(str(out))} "
                        f"{q(coords['name'] + '==' + coords['version'])}", ctx.log)
        return sha256_dir(out)


def sha256_b64(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


class Helm(Adapter):
    name = "helm"

    def build(self, ctx, name):
        chart = ctx.tmp("chart") / name
        (chart / "templates").mkdir(parents=True)
        (chart / "Chart.yaml").write_text(f"apiVersion: v2\nname: {name}\nversion: 1.0.0\n"
                                          "description: Artifactory upgrade test\n")
        (chart / "templates" / "configmap.yaml").write_text(
            f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {name}\n")
        out = ctx.tmp("build")
        ctx.run("helm", f"helm package {q(str(chart))} -d {q(str(out))}", ctx.log)
        path = out / f"{name}-1.0.0.tgz"
        return Artifact({"chart": name, "version": "1.0.0"}, {path.name: sha256_file(path)}, path)

    def push(self, ctx, repo, art):
        ctx.run("curl", f'curl -fsS --oauth2-bearer "$ARTIFACTORY_TOKEN" -T {q(str(art.path))} '
                        f'{q(f"{ctx.config.url}/{repo}/{art.path.name}")}', ctx.log)

    def pull(self, ctx, repo, coords):
        out = ctx.tmp("pull")
        home = f"{q(str(out))}/.helm"
        ctx.run("helm", f"HELM_CACHE_HOME={home}/cache HELM_CONFIG_HOME={home}/config HELM_DATA_HOME={home}/data "
                        f"helm pull {q(coords['chart'])} --version {q(coords['version'])} "
                        f"--repo {q(f'{ctx.config.url}/api/helm/{repo}')} "
                        f'--username "$ARTIFACTORY_USER" --password "$ARTIFACTORY_TOKEN" -d {q(str(out))}', ctx.log)
        return {p.name: sha256_file(p) for p in out.glob("*.tgz")}


class Docker(Adapter):
    """Images move through skopeo's dir: transport, which keeps manifests and blobs byte-identical."""
    name = "docker"

    def tls(self, ctx, flag):
        return f"{flag}=false" if ctx.config.insecure else ""

    def ref(self, ctx, repo, coords):
        sep = "@" if coords["reference"].startswith("sha256:") else ":"
        return f"docker://{ctx.config.docker_prefix(repo)}/{coords['image']}{sep}{coords['reference']}"

    def build(self, ctx, name):
        out = ctx.tmp("image")
        layer, layer_tar = targz({"aut.txt": payload(name)})
        config = json.dumps({"architecture": "amd64", "os": "linux", "config": {},
                             "rootfs": {"type": "layers", "diff_ids": ["sha256:" + sha256_bytes(layer_tar)]}},
                            sort_keys=True).encode()
        manifest = json.dumps({
            "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                       "digest": "sha256:" + sha256_bytes(config), "size": len(config)},
            "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                        "digest": "sha256:" + sha256_bytes(layer), "size": len(layer)}],
        }, sort_keys=True).encode()
        for blob in (config, layer):
            (out / sha256_bytes(blob)).write_bytes(blob)
        (out / "manifest.json").write_bytes(manifest)
        (out / "version").write_text("Directory Transport Version: 1.1\n")
        sums = sha256_dir(out, exclude={"version"})
        sums["manifest.raw"] = sums["manifest.json"]
        return Artifact({"image": name, "reference": "1.0.0"}, sums, out)

    def push(self, ctx, repo, art):
        ctx.run("docker", f'skopeo copy --preserve-digests --dest-creds "$ARTIFACTORY_USER:$ARTIFACTORY_TOKEN" '
                          f"{self.tls(ctx, '--dest-tls-verify')} dir:{q(str(art.path))} {q(self.ref(ctx, repo, art.coords))}", ctx.log)

    def pull(self, ctx, repo, coords):
        out = ctx.tmp("pull")
        ref = q(self.ref(ctx, repo, coords))
        creds = '"$ARTIFACTORY_USER:$ARTIFACTORY_TOKEN"'
        # The raw manifest is what the registry serves (an index for multi-arch images);
        # the copy resolves it to linux/amd64 and stores that manifest and its blobs.
        ctx.run("docker", f"skopeo inspect --raw --creds {creds} {self.tls(ctx, '--tls-verify')} "
                          f"{ref} > {q(str(out))}/manifest.raw && "
                          f"skopeo copy --src-creds {creds} {self.tls(ctx, '--src-tls-verify')} --override-os linux "
                          f"--override-arch amd64 {ref} dir:{q(str(out))}/image", ctx.log)
        sums = sha256_dir(out / "image", exclude={"version"})
        sums["manifest.raw"] = sha256_file(out / "manifest.raw")
        return sums

    def cache_names(self, sums):
        return sorted(f"sha256__{k}" for k in sums if re.fullmatch(r"[0-9a-f]{64}", k))


ADAPTERS = {a.name: a for a in (Docker(), Maven(), Npm(), PyPI(), Helm(), Generic())}
