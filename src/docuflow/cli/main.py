from __future__ import annotations

import sys

import click
import structlog

from docuflow import __version__
from docuflow.constants import DEFAULT_DPI

logger = structlog.get_logger()


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """docuflow - Production workflow runtime for document agents."""


@main.command()
@click.argument("file_path")
@click.option("--schema", "-s", required=True, help="Schema name or dotted Python path")
@click.option("--model", "-m", default="openai/gpt-4o", help="LLM model to use")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
@click.option("--store", default=None, help="Storage backend (e.g., 'local')")
def extract(
    file_path: str,
    schema: str,
    model: str,
    output: str | None,
    store: str | None,
) -> None:
    """Extract structured data from a document."""
    from docuflow.api import extract_sync
    from docuflow.cli.utils import load_schema

    try:
        schema_cls = load_schema(schema)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        click.echo(f"Error loading schema: {exc}", err=True)
        sys.exit(1)

    try:
        result = extract_sync(file_path, schema=schema_cls, model=model, storage=store)
    except Exception as exc:
        click.echo(f"Extraction failed: {exc}", err=True)
        sys.exit(1)

    json_output = result.model_dump_json(indent=2)

    if output:
        with open(output, "w") as f:
            f.write(json_output)
        click.echo(f"Result written to {output}")
    else:
        click.echo(json_output)


@main.command(name="extract-folder")
@click.argument("folder_path")
@click.option("--schema", "-s", required=True, help="Schema name or dotted Python path")
@click.option("--model", "-m", default="openai/gpt-4o", help="LLM model to use")
@click.option("--parser", "-p", default="auto", help="Parser: auto, pdfplumber, tesseract, docling, smart, azure-di, textract, google-docai")
@click.option("--output", "-o", default=None, help="Output CSV file path")
@click.option("--pattern", default="**/*.pdf", help="File glob pattern")
@click.option("--concurrency", "-c", default=5, help="Max concurrent extractions")
def extract_folder(
    folder_path: str,
    schema: str,
    model: str,
    parser: str,
    output: str | None,
    pattern: str,
    concurrency: int,
) -> None:
    """Extract structured data from all documents in a folder."""
    from pathlib import Path

    from docuflow.batch import process_batch_sync
    from docuflow.cli.utils import load_schema
    from docuflow.processor import DocumentPipeline

    try:
        schema_cls = load_schema(schema)
    except (ValueError, ImportError, AttributeError, TypeError) as exc:
        click.echo(f"Error loading schema: {exc}", err=True)
        sys.exit(1)

    folder = Path(folder_path)
    if not folder.is_dir():
        click.echo(f"Not a directory: {folder_path}", err=True)
        sys.exit(1)

    files = sorted(str(p) for p in folder.glob(pattern) if p.is_file())
    if not files:
        click.echo(f"No files matching '{pattern}' in {folder_path}")
        sys.exit(0)

    click.echo(f"Processing {len(files)} files...")

    pipeline = DocumentPipeline(parser=parser, model=model)

    try:
        report = process_batch_sync(files, schema=schema_cls, pipeline=pipeline, concurrency=concurrency)
    except Exception as exc:
        click.echo(f"Batch processing failed: {exc}", err=True)
        sys.exit(1)

    click.echo("\nResults:")
    click.echo(f"  Total:        {report.total}")
    click.echo(f"  Succeeded:    {report.succeeded}")
    click.echo(f"  Failed:       {report.failed}")
    click.echo(f"  Needs review: {report.needs_review}")
    click.echo(f"  Avg trust-gate rate: {report.average_confidence:.2f}")

    if report.top_review_reasons:
        click.echo("\nTop review reasons:")
        for reason, count in report.top_review_reasons.items():
            click.echo(f"  {count}x {reason}")

    if output:
        csv_text = report.to_csv()
        with open(output, "w") as f:
            f.write(csv_text)
        click.echo(f"\nCSV written to {output}")
    else:
        click.echo("\nUse --output results.csv to export data")


@main.command()
@click.argument("config_path")
@click.argument("file_path")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
def run(config_path: str, file_path: str, output: str | None) -> None:
    """Run a workflow from a YAML config file."""
    from pathlib import Path

    from docuflow.workflow_config import run_workflow_sync

    config = Path(config_path)
    if not config.is_file():
        click.echo(f"Config not found: {config_path}", err=True)
        sys.exit(1)

    try:
        result = run_workflow_sync(config, file_path)
    except Exception as exc:
        click.echo(f"Workflow failed: {exc}", err=True)
        sys.exit(1)

    json_output = result.model_dump_json(indent=2)

    if output:
        with open(output, "w") as f:
            f.write(json_output)
        click.echo(f"Result written to {output}")
    else:
        click.echo(json_output)


@main.command()
@click.argument("file_path")
@click.option("--output", "-o", required=True, help="Output directory for screenshots")
@click.option("--dpi", default=DEFAULT_DPI, help="DPI for rendering")
@click.option("--pages", default=None, help="Page numbers (e.g. '0,1,2' or leave empty for all)")
def screenshot(
    file_path: str,
    output: str,
    dpi: int,
    pages: str | None,
) -> None:
    """Render document pages as PNG images."""
    from docuflow.screenshots import screenshot_pages_sync

    page_list = None
    if pages:
        page_list = [int(p.strip()) for p in pages.split(",")]

    try:
        results = screenshot_pages_sync(file_path, output_dir=output, pages=page_list, dpi=dpi)
    except Exception as exc:
        click.echo(f"Screenshot failed: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Generated {len(results)} screenshot(s):")
    for r in results:
        click.echo(f"  Page {r.page_number}: {r.width}x{r.height} -> {r.file_path}")


@main.command()
@click.argument("config_path")
@click.option("--host", default="0.0.0.0", help="Host to bind to")  # noqa: S104
@click.option("--port", "-p", default=8000, help="Port to bind to")
def serve(config_path: str, host: str, port: int) -> None:
    """Start an HTTP server for a workflow config."""
    from pathlib import Path

    config = Path(config_path)
    if not config.is_file():
        click.echo(f"Config not found: {config_path}", err=True)
        sys.exit(1)

    try:
        from docuflow.serve import run_server
    except ImportError:
        click.echo(
            "Serve dependencies not installed. Run: pip install docuflow[serve]",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Starting DocuFlow server on {host}:{port}")
    click.echo(f"Workflow: {config_path}")
    click.echo(f"POST http://{host}:{port}/extract  — upload a file")
    click.echo(f"GET  http://{host}:{port}/health   — health check")
    click.echo(f"GET  http://{host}:{port}/schema   — field definitions")
    run_server(config_path, host=host, port=port)


@main.command()
@click.argument("config_path")
@click.option("--output", "-o", default="./deploy", help="Output directory")
@click.option("--port", "-p", default=8000, help="Exposed port in docker-compose")
@click.option("--with-storage", is_flag=True, help="Add persistent volume for storage and logs")
def dockerize(config_path: str, output: str, port: int, with_storage: bool) -> None:
    """Generate a Docker deployment for a workflow config."""
    from pathlib import Path

    config = Path(config_path)
    if not config.is_file():
        click.echo(f"Config not found: {config_path}", err=True)
        sys.exit(1)

    from docuflow.dockerize import generate_deployment

    try:
        out = generate_deployment(config_path, output, port=port, with_storage=with_storage)
    except Exception as exc:
        click.echo(f"Failed: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Deployment generated in {out}/")
    click.echo("  Dockerfile")
    click.echo("  server.py")
    click.echo("  workflow.yaml")
    click.echo("  docker-compose.yml")
    click.echo("  requirements.txt")
    click.echo()
    click.echo("Next steps:")
    click.echo(f"  cd {out}")
    click.echo("  docker compose up --build")


@main.command(name="route")
@click.argument("routes_path")
@click.argument("input_path")
@click.option("--output", "-o", default=None, help="Output CSV file path")
@click.option("--pattern", default="**/*.pdf", help="File glob pattern for folders")
@click.option("--concurrency", "-c", default=5, help="Max concurrent documents")
def route(
    routes_path: str,
    input_path: str,
    output: str | None,
    pattern: str,
    concurrency: int,
) -> None:
    """Classify documents in INPUT_PATH and run the matching workflow from ROUTES_PATH."""
    from pathlib import Path

    from docuflow.router import WorkflowRouter

    router = WorkflowRouter.from_config(routes_path)

    path = Path(input_path)
    files = (
        [str(path)] if path.is_file()
        else sorted(str(p) for p in path.glob(pattern))
    )
    if not files:
        click.echo(f"No files found in {input_path}")
        raise SystemExit(1)

    report = router.route_sync(files, concurrency=concurrency)

    click.echo(f"Routed {report.total} document(s):")
    for name, results in report.by_workflow.items():
        ok = len([r for r in results if r.success])
        click.echo(f"  {name}: {len(results)} ({ok} succeeded)")
    if report.unclassified:
        click.echo(f"  unclassified: {len(report.unclassified)}")
        for r in report.unclassified:
            click.echo(f"    {r.file_name}: {r.classification_reason}")
    if report.usage:
        click.echo(
            f"Tokens: {report.usage.total_tokens} across "
            f"{report.usage.n_llm_calls} LLM calls"
        )

    if output:
        Path(output).write_text(report.to_csv(), encoding="utf-8")
        click.echo(f"Results written to {output}")


@main.group(name="templates")
def templates_group() -> None:
    """Manage extraction templates."""


@templates_group.command(name="list")
def templates_list() -> None:
    """List available templates."""
    from docuflow.templates.registry import list_templates

    templates = list_templates()
    if not templates:
        click.echo("No templates found.")
        return

    click.echo(f"{'Name':<20} {'Version':<10} {'Source':<10} {'Description'}")
    click.echo("-" * 70)
    for t in templates:
        click.echo(f"{t.name:<20} {t.version:<10} {t.source:<10} {t.description}")


@templates_group.command(name="show")
@click.argument("name")
def templates_show(name: str) -> None:
    """Show a template's YAML definition."""
    import yaml

    from docuflow.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    try:
        data = registry.load_raw(name)
    except FileNotFoundError:
        click.echo(f"Template not found: {name}", err=True)
        sys.exit(1)

    click.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))


@templates_group.command(name="init")
@click.argument("name")
@click.option("--dir", "target_dir", default=None, help="Target directory")
def templates_init(name: str, target_dir: str | None) -> None:
    """Copy a built-in template to your project for customization."""
    import shutil
    from pathlib import Path

    from docuflow.templates.registry import _BUILTIN_DIR

    src = None
    for ext in (".yaml", ".yml"):
        candidate = _BUILTIN_DIR / f"{name}{ext}"
        if candidate.is_file():
            src = candidate
            break

    if src is None:
        click.echo(f"Built-in template not found: {name}", err=True)
        sys.exit(1)

    dest_dir = Path(target_dir) if target_dir else Path("docuflow_templates")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(str(src), str(dest))
    click.echo(f"Template '{name}' copied to {dest}")
    click.echo("Edit this file to customize the schema.")
