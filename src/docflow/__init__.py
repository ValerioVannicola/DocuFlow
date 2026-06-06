"""docflow: Production workflow runtime for document agents."""

from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    if name == "extract":
        from docflow.api import extract_sync

        return extract_sync
    if name == "extract_async":
        from docflow.api import extract

        return extract
    if name == "DocumentPipeline":
        from docflow.processor import DocumentPipeline

        return DocumentPipeline
    if name == "Pipeline":
        from docflow.workflow.pipeline import Pipeline

        return Pipeline
    if name == "PrivacyPolicy":
        from docflow.privacy.policy import PrivacyPolicy

        return PrivacyPolicy
    if name == "compare_documents":
        from docflow.comparison import compare_documents_sync

        return compare_documents_sync
    if name == "compare_documents_async":
        from docflow.comparison import compare_documents

        return compare_documents
    if name == "process_batch":
        from docflow.batch import process_batch_sync

        return process_batch_sync
    if name == "process_batch_async":
        from docflow.batch import process_batch

        return process_batch
    if name == "quality_report":
        from docflow.quality import quality_report

        return quality_report
    if name == "QualityLog":
        from docflow.quality import QualityLog

        return QualityLog
    if name == "QualitySnapshot":
        from docflow.quality import QualitySnapshot

        return QualitySnapshot
    if name == "run_workflow":
        from docflow.workflow_config import run_workflow_sync

        return run_workflow_sync
    if name == "run_workflow_async":
        from docflow.workflow_config import run_workflow

        return run_workflow
    if name == "load_workflow_config":
        from docflow.workflow_config import load_workflow_config

        return load_workflow_config
    if name == "WorkflowConfig":
        from docflow.workflow_config import WorkflowConfig

        return WorkflowConfig
    if name == "discover_schema":
        from docflow.discover import discover_schema_sync

        return discover_schema_sync
    if name == "discover_schema_async":
        from docflow.discover import discover_schema

        return discover_schema
    raise AttributeError(f"module 'docflow' has no attribute {name!r}")


__all__ = [
    "DocumentPipeline",
    "Pipeline",
    "PrivacyPolicy",
    "__version__",
    "extract",
    "extract_async",
]
