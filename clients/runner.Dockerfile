FROM python:3.13-slim
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN pip install --no-cache-dir pytest==8.3.4 pyyaml==6.0.2
