"""FastAPI server for running DocuFlow workflows as an HTTP service."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from docuflow.quality import quality_report
from docuflow.workflow_config import WorkflowConfig, load_workflow_config


def create_app(config: WorkflowConfig) -> FastAPI:
    """Create a FastAPI app that serves a single workflow config."""

    app = FastAPI(
        title=f"DocuFlow — {config.name}",
        version=config.version,
        description=config.description or f"Document extraction service: {config.name}",
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "workflow": config.name,
            "version": config.version,
            "model": config.model,
            "parser": config.parser,
        }

    @app.get("/schema")
    def schema() -> dict[str, Any]:
        return {
            "workflow": config.name,
            "fields": config.schema_,
        }

    @app.post("/extract")
    async def extract(file: UploadFile = File(...)) -> JSONResponse:  # noqa: B008 — FastAPI idiom
        suffix = Path(file.filename).suffix if file.filename else ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            pipeline = config.build_pipeline()
            schema_cls = config.build_schema()
            result = pipeline.run_sync(tmp_path, schema_cls)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        report = quality_report(result)

        response = result.model_dump(mode="json")
        response["quality_score"] = report.score
        response["quality_ok"] = report.ok

        return JSONResponse(content=response)

    return app


def run_server(
    config_source: str | Path | dict,
    host: str = "0.0.0.0",  # noqa: S104 — bind-all is intended for containers
    port: int = 8000,
) -> None:
    """Load a workflow config and start the server."""
    import uvicorn

    config = load_workflow_config(config_source)
    app = create_app(config)
    uvicorn.run(app, host=host, port=port)
