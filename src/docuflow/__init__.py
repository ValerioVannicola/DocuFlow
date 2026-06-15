"""docuflow: Production workflow runtime for document agents."""

from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    if name == "extract":
        from docuflow.api import extract_sync

        return extract_sync
    if name == "extract_async":
        from docuflow.api import extract

        return extract
    if name == "DocumentPipeline":
        from docuflow.processor import DocumentPipeline

        return DocumentPipeline
    if name == "Pipeline":
        from docuflow.workflow.pipeline import Pipeline

        return Pipeline
    if name == "PrivacyPolicy":
        from docuflow.privacy.policy import PrivacyPolicy

        return PrivacyPolicy
    if name == "compare_documents":
        from docuflow.comparison import compare_documents_sync

        return compare_documents_sync
    if name == "compare_documents_async":
        from docuflow.comparison import compare_documents

        return compare_documents
    if name == "process_batch":
        from docuflow.batch import process_batch_sync

        return process_batch_sync
    if name == "process_batch_async":
        from docuflow.batch import process_batch

        return process_batch
    if name == "quality_report":
        from docuflow.quality import quality_report

        return quality_report
    if name == "QualityLog":
        from docuflow.quality import QualityLog

        return QualityLog
    if name == "QualitySnapshot":
        from docuflow.quality import QualitySnapshot

        return QualitySnapshot
    if name == "run_workflow":
        from docuflow.workflow_config import run_workflow_sync

        return run_workflow_sync
    if name == "run_workflow_async":
        from docuflow.workflow_config import run_workflow

        return run_workflow
    if name == "load_workflow_config":
        from docuflow.workflow_config import load_workflow_config

        return load_workflow_config
    if name == "WorkflowConfig":
        from docuflow.workflow_config import WorkflowConfig

        return WorkflowConfig
    if name == "discover_schema":
        from docuflow.discover import discover_schema_sync

        return discover_schema_sync
    if name == "discover_schema_async":
        from docuflow.discover import discover_schema

        return discover_schema
    if name == "WorkflowRouter":
        from docuflow.router import WorkflowRouter

        return WorkflowRouter
    if name == "RoutedReport":
        from docuflow.router import RoutedReport

        return RoutedReport
    if name == "highlight_fields":
        from docuflow.rendering.highlight import highlight_fields

        return highlight_fields
    if name == "highlight_fields_async":
        from docuflow.rendering.highlight import highlight_fields_async

        return highlight_fields_async
    if name == "fill_pdf_form":
        from docuflow.filling.api import fill_pdf_form

        return fill_pdf_form
    if name == "fill_pdf_form_async":
        from docuflow.filling.api import fill_pdf_form_async

        return fill_pdf_form_async
    if name == "fill_docx_form":
        from docuflow.filling.api import fill_docx_form

        return fill_docx_form
    if name == "fill_docx_form_async":
        from docuflow.filling.api import fill_docx_form_async

        return fill_docx_form_async
    if name == "commit_fill":
        from docuflow.filling.api import commit_fill

        return commit_fill
    if name == "commit_fill_async":
        from docuflow.filling.api import commit_fill_async

        return commit_fill_async
    if name == "preview_fill":
        from docuflow.filling.preview import preview_fill

        return preview_fill
    if name == "preview_fill_async":
        from docuflow.filling.preview import preview_fill_async

        return preview_fill_async
    if name == "FillingResult":
        from docuflow.filling.models import FillingResult

        return FillingResult
    if name == "split_document":
        from docuflow.splitting.api import split_document

        return split_document
    if name == "split_document_async":
        from docuflow.splitting.api import split_document_async

        return split_document_async
    if name == "DocumentSection":
        from docuflow.splitting.models import DocumentSection

        return DocumentSection
    if name == "SplitResult":
        from docuflow.splitting.models import SplitResult

        return SplitResult
    if name == "extract_metadata":
        from docuflow.metadata.api import extract_metadata

        return extract_metadata
    if name == "extract_metadata_async":
        from docuflow.metadata.api import extract_metadata_async

        return extract_metadata_async
    if name == "DocumentMetadataResult":
        from docuflow.metadata.models import DocumentMetadataResult

        return DocumentMetadataResult
    raise AttributeError(f"module 'docuflow' has no attribute {name!r}")


__all__ = [
    "DocumentPipeline",
    "FillingResult",
    "Pipeline",
    "PrivacyPolicy",
    "WorkflowRouter",
    "__version__",
    "commit_fill",
    "commit_fill_async",
    "extract",
    "extract_async",
    "fill_docx_form",
    "fill_docx_form_async",
    "fill_pdf_form",
    "fill_pdf_form_async",
    "preview_fill",
    "preview_fill_async",
    "split_document",
    "split_document_async",
    "extract_metadata",
    "extract_metadata_async",
    "DocumentMetadataResult",
]
