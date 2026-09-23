# Local AI QA infrastructure

This directory provides a reproducible local infrastructure layer for the QA lab.

It builds Skyvern from a pinned upstream Git tag and runs:

- PostgreSQL
- Ollama with NVIDIA GPU access
- the selected Ollama model
- Skyvern API + embedded browser
- optional Skyvern UI

## Why Docker Compose

Docker Compose owns the local services. Terraform is intentionally not used for
local containers; Terraform is better reserved for provisioning the machine,
network, storage and firewall when the lab is moved to a VM/cloud environment.

## Prerequisites

- Docker + Docker Compose v2
- Git
- NVIDIA driver
- NVIDIA Container Toolkit for GPU acceleration

The Ollama service requests an NVIDIA GPU. On a CPU-only machine, remove the
GPU reservation from `docker-compose.yml`.

## Bootstrap

```bash
cd infra/local
cp .env.example .env
make bootstrap
make up
```

The bootstrap script clones the Skyvern source at `SKYVERN_VERSION` into the
ignored `.runtime/` directory. The container image is built from that checkout,
so the backend is aligned with the version declared by the lab instead of
implicitly pulling `latest`.

## Check services

```bash
make ps
make health
```

Expected endpoints:

```text
Skyvern API  http://localhost:8000
Ollama       http://localhost:11434
```

Optional Skyvern UI:

```bash
make ui
```

Then open:

```text
http://localhost:8080
```

## API key

The self-hosted startup creates local credentials under `.skyvern/`.

Print the generated key:

```bash
make key
```

Copy it to the QA environment:

```env
SKYVERN_BASE_URL=http://localhost:8000
SKYVERN_API_KEY=<output of make key>
```

Never commit the generated key.

## Model

Default:

```text
gemma4:e4b
```

Change `OLLAMA_MODEL` in `.env`, then:

```bash
make pull-model
docker compose restart skyvern
```

## Minikube connectivity

The browser embedded in the Skyvern container must be able to reach the banking
application itself. Host reachability is not enough.

Configure:

```env
TARGET_URL=http://192.168.49.2:30081/
SKYVERN_ALLOWED_HOSTS=["192.168.49.2"]
```

Then:

```bash
make check-target
```

If that check fails, do not change the tests yet. Expose the Minikube service
through the host and use `host.docker.internal:<port>` as `TARGET_URL`/`BASE_URL`,
or add the required Docker-to-Minikube route.

## Important migration note

The currently validated QA implementation launches a browser from the Python
test process. The Dockerized Skyvern service has its own embedded browser.

Do not switch the test suite to this stack until `support/browser.py` is adapted
to use the browser/session owned by self-hosted Skyvern. Keeping a browser on
the host while moving only Skyvern into Docker can produce a broken
`localhost`/CDP path.

Recommended migration order:

1. Bring this stack up.
2. Validate Ollama and Skyvern health.
3. Validate `make check-target`.
4. Adapt `support/browser.py` to the self-hosted browser/session model.
5. Run one authentication smoke.
6. Only then make Docker Compose the default quickstart.
