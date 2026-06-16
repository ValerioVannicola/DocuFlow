"""Generate a self-contained deployment directory for a DocuFlow workflow."""

from __future__ import annotations

import shutil
from pathlib import Path

from docuflow.workflow_config import load_workflow_config

_DOCKERFILE = """\
FROM python:3.11-slim
{system_deps}
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
"""

_TESSERACT_APT = """
RUN apt-get update && apt-get install -y --no-install-recommends \\
    tesseract-ocr && rm -rf /var/lib/apt/lists/*
"""

_SERVER_PY = """\
\"\"\"Auto-generated DocuFlow server — do not edit manually.\"\"\"

from docuflow.serve import create_app
from docuflow.workflow_config import load_workflow_config

config = load_workflow_config("workflow.yaml")
app = create_app(config)
"""

def _required_extras(config) -> tuple[set[str], bool]:
    """Derive the docuflow extras and system deps the workflow needs.

    Returns (extras, needs_tesseract_binary)."""
    extras = {"llm", "serve"}
    needs_tesseract = False

    parser = config.parser_type
    extraction = config.extraction_type

    if parser == "auto":
        extras.update({"pdf", "ocr", "docling"})
        needs_tesseract = True
    if parser in ("pdfplumber", "smart") or extraction in ("vision", "hybrid", "auto"):
        extras.add("pdf")
    if parser in ("tesseract", "smart") or extraction in ("vision", "hybrid", "auto"):
        extras.update({"pdf", "ocr"})
        needs_tesseract = True
    if parser == "docling":
        extras.add("docling")
    if parser == "azure-di":
        extras.add("azure")
    if parser == "textract":
        extras.update({"aws", "pdf"})
    if parser == "google-docai":
        extras.add("gcp")
    if config.privacy:
        extras.add("privacy")

    return extras, needs_tesseract

_DOCKER_COMPOSE = """\
services:
  docuflow:
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
      - docuflow_data:/data"""

_COMPOSE_VOLUMES_DEF = """\
volumes:
  docuflow_data:"""


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

    config = load_workflow_config(config_path)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    extras, needs_tesseract = _required_extras(config)
    requirements = f"docuflow[{','.join(sorted(extras))}]\n"
    dockerfile = _DOCKERFILE.format(
        system_deps=_TESSERACT_APT if needs_tesseract else "",
    )

    shutil.copy2(str(config_path), str(out / "workflow.yaml"))
    (out / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (out / "server.py").write_text(_SERVER_PY, encoding="utf-8")
    (out / "requirements.txt").write_text(requirements, encoding="utf-8")

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
