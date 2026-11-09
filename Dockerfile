# All-in-one runner: the suite plus every native client it drives
# (skopeo, mvn, npm, pip/twine, helm, curl).
FROM python:3.13-slim-trixie

COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/openjdk
COPY --from=maven:3.9-eclipse-temurin-21 /usr/share/maven /usr/share/maven
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=alpine/helm:3.16.3 /usr/bin/helm /usr/local/bin/helm

ENV JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends skopeo curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && ln -s /usr/share/maven/bin/mvn /usr/local/bin/mvn \
 && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && pip install --no-cache-dir pytest==8.3.4 pyyaml==6.0.2 twine==6.0.1 \
 && skopeo --version && mvn -v | head -1 && npm -v && helm version --short && twine --version | head -1

# The suite itself, so the image also runs without a checkout:
#   docker run -e ARTIFACTORY_URL -e ARTIFACTORY_TOKEN -v $PWD/out:/opt/aut/out <image> python -m aut pre
WORKDIR /opt/aut
COPY aut aut
COPY suite_tests suite_tests
COPY config.yaml .
