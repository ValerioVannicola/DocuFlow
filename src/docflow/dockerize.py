"""Generate a self-contained deployment directory for a DocFlow workflow."""

from __future__ import annotations

import shutil
from pathlib import Path

from docflow.workflow_config import load_workflow_config

_DOCKERFILE = """\
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
"""

_SERVER_PY = """\
\"\"\"Auto-generated DocFlow server — do not edit manually.\"\"\"

from docflow.serve import create_app
from docflow.workflow_config import load_workflow_config

config = load_workflow_config("workflow.yaml")
app = create_app(config)
"""

_REQUIREMENTS = """\
docflow[pdf,llm]
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9
"""

_DOCKER_COMPOSE = """\
services:
  docflow:
    build: .
    ports:
      - "{port}:8000"
    environment:
      - GEMINI_API_KEY=${{GEMINI_API_KEY:-}}
      - OPENAI_API_KEY=${{OPENAI_API_KEY:-}}
      - ANTHROPIC_API_KEY=${{ANTHROPIC_API_KEY:-}}
{volumes_section}
{volumes_def}
"""

_COMPOSE_VOLUMES_SECTION = """\
    volumes:
      - docflow_data:/data"""

_COMPOSE_VOLUMES_DEF = """\
volumes:
  docflow_data:"""


def generate_deployment(
    config_source: str | Path,
    output_dir: str | Path,
    port: int = 8000,
    with_storage: bool = False,
) -> Path:
    """Generate a deployment directory with Dockerfile, server, and compose."""
    config_path = Path(config_source)
    if not config_path.is_file():
        raise FileNotFoundError(f"Workflow config not found: {config_path}")

    load_workflow_config(config_path)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    shutil.copy2(str(config_path), str(out / "workflow.yaml"))
    (out / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
    (out / "server.py").write_text(_SERVER_PY, encoding="utf-8")
    (out / "requirements.txt").write_text(_REQUIREMENTS, encoding="utf-8")

    volumes_section = _COMPOSE_VOLUMES_SECTION if with_storage else ""
    volumes_def = _COMPOSE_VOLUMES_DEF if with_storage else ""

    compose = _DOCKER_COMPOSE.format(
        port=port,
        volumes_section=volumes_section,
        volumes_def=volumes_def,
    )
    (out / "docker-compose.yml").write_text(compose, encoding="utf-8")

    (out / ".dockerignore").write_text(
        "__pycache__\n*.pyc\n.git\n.env\n",
        encoding="utf-8",
    )

    return out
