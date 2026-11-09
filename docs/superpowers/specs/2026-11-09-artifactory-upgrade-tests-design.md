# Artifactory Upgrade Tests Design

## Intent and Scope

Build the suite described in `SPEC.md` for operators checking an Artifactory upgrade. Exercise Docker, Maven, npm, PyPI, Helm, and Generic repositories across Local, Remote, and Virtual types. Preserve evidence from before the upgrade and make failures inspectable in a standalone HTML report, JUnit XML, and JSON.

The workspace currently contains only the specification. All choices below are proposals for approval; the specification remains authoritative.

## Approaches

Use one Python/pytest runner controlling six Docker Compose client services. Each service contains its native client. This keeps manifests, phase ordering, and reporting in one process while testing real package protocols. This is the recommended approach.

Running pytest independently inside each client container would isolate execution further, but require merging six sets of results and coordinating shared state. A Python HTTP-only implementation would reduce containers but would omit the native clients required by the specification.

## Execution and Configuration

Provide `./run.sh pre` and `./run.sh post`, with explicit configuration and output-directory options. Compose runs the Python runner and format clients on a shared network. A separate development Compose file starts a version-selectable Artifactory instance with a persistent volume. Existing instances require only the URL, access token, and repository configuration, as specified.

Validate YAML configuration before starting tests. Configure repository names for all 18 combinations, public upstream coordinates, and whether each Virtual repository has a default deployment target. Read credentials from environment variables, avoid command-line token arguments where possible, and redact credentials from persisted logs. Reserve proxy environment forwarding in Compose; proxy-specific behavior remains deferred.

Use a unique run ID for every phase. Namespace all generated package names, versions, and paths with that ID. Keep existing manifests intact and write phase outputs atomically. A post run explicitly selects the pre manifest; the default points to the most recent completed pre run in the output directory. Preserve partial results if individual tests fail.

## Format Behavior

| Format | Native Client | Generated Local Artifact | Remote Input |
|---|---|---|---|
| Docker | skopeo | Small OCI image with a run-specific layer and tag | Configured image pinned by digest |
| Maven | mvn | Minimal JAR and POM with unique coordinates | Configured fixed group, artifact, and version |
| npm | npm | Minimal tarball with unique name and version | Configured fixed package and version |
| PyPI | pip and twine | Minimal Python distribution with unique name and version | Configured fixed distribution and version |
| Helm | helm | Minimal packaged chart with unique version | Configured fixed chart and version |
| Generic | curl | Run-specific binary file | Configured public object path |

Local tests publish, fetch using a fresh client cache, and compare SHA-256. Remote tests fetch configured upstream artifacts through Artifactory twice using fresh client caches, compare bytes, and inspect Artifactory cache metadata to establish server-side caching. Record the cache evidence and any API failure in the result.

Virtual tests fetch through the Virtual endpoint, exercising both its Local and Remote members. If a default deployment repository is configured, also publish through Virtual and fetch the result. A missing deployment target is a recorded non-applicable sub-operation; Virtual pulls must still pass. Seed Local before testing its Virtual member.

Checksums refer to downloaded package bytes. For container images, record the manifest digest and SHA-256 checksums of the manifest, configuration, and layer blobs. Avoid comparing mutable metadata or rebuilt archives. Use fixed upstream versions or digests and store the resolved identity in the manifest.

## Manifest and Phase Ordering

The versioned JSON manifest records the source run ID, format, repository type, actual deployment repository, retrieval endpoint, immutable coordinates, and expected checksums. It contains no credentials. Include fetched Remote artifacts so post also checks their previous identities.

`pre` runs the 18 combinations and stores each successful artifact as soon as it is verified. It finishes with a nonzero exit status if any required operation failed.

`post` first validates the supplied manifest, then retrieves every recorded artifact using its original coordinates and compares checksums. It next runs all 18 combinations with a fresh run ID, even if old-artifact checks fail. Missing old artifacts remain failures even when fresh push/pull succeeds. Manifest entries must resolve through the configured Artifactory instance; reject external retrieval URLs to avoid leaking credentials.

## Reports

Produce one self-contained HTML file with an 18-row matrix and separate columns for pre, old-artifact retrieval, and fresh post results. Show absent phases as pending. Include expandable operation logs and escaped error text. Use status labels alongside colors. Persist normalized JSON results and emit JUnit cases for both retention and fresh operations, with failed operations affecting the process exit status.

## Development Setup

Provide a setup script that waits for Artifactory readiness, obtains an access token through the API using operator-supplied bootstrap credentials, and creates the dedicated Local, Remote, and Virtual repositories. Configure Virtual members and default deployment targets explicitly. Do not overwrite existing repositories with incompatible settings. Store any local credential file outside version control and restrict its permissions.

Use an Artifactory Pro or trial image for development, subject to confirming current image availability and license requirements. Treat six-format license support as a prerequisite; do not assume the Container Registry edition supports every required format. Document startup, setup, pre, manual image upgrade with the persistent volume, post, and deliberate artifact deletion to check detection. Repository cleanup is an explicit operator action.

## Verification

Use unit tests for configuration validation, manifest validation and persistence, report escaping and matrix completeness, checksum failures, command construction, and failure aggregation. Use stub client execution for runner tests, including a missing old artifact followed by successful fresh operations.

Validate Compose configuration and shell entry points. Run the full pre/upgrade/post scenario and deletion check against a local licensed Artifactory instance when Docker access, image pulls, and a license are available. Report any unavailable live checks explicitly; mocked tests cannot establish protocol or edition compatibility.

## Implementation Sequence

1. Add validated configuration, result models, manifest persistence, and the pytest runner.
2. Add Compose services and native client adapters for all six formats.
3. Implement pre, retention checks, fresh post execution, and failure aggregation.
4. Add standalone HTML, JSON, and JUnit outputs.
5. Add the development stack, repository/token setup, and operator documentation.
6. Run focused tests and available live checks; record remaining environment prerequisites.

## Non-Goals

The suite does not perform the Artifactory upgrade, manage production repositories, add CI deployment, implement custom proxy handling, or automatically delete repositories. It does not silently skip required formats when the selected edition lacks support.