from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docuflow._sync import run_sync
from docuflow.constants import DEFAULT_DPI
from docuflow.extraction.models import ExtractionResult
from docuflow.ingestion.mime import SourceKind, detect_source_kind


class DocumentPipeline:
    """Configure and run DocuFlow extraction pipelines.

    This is the main reusable user-facing pipeline object. It selects a parser,
    applies optional privacy, validation, review, and verification steps, and
    returns an :class:`~docuflow.extraction.models.ExtractionResult`.

    Args:
        parser: Parser selector, parser config dict, parser object, or ``"auto"``.
        model: LLM model name passed to LiteLLM.
        storage: Optional storage backend name, config, or instance.
        validators: Optional validation rules.
        review_rules: Optional review rules.
        privacy: Optional privacy policy.
        extraction_mode: ``"single"`` or ``"multi"``.
        extraction_type: ``"text"``, ``"vision"``, ``"hybrid"``, or ``"auto"``.
        n_instances: Number of parallel LLM candidates in multi mode.
        temperatures: Optional candidate temperatures for multi mode.
        vision_dpi: Render DPI used for vision-based steps.
        context: Optional domain instructions injected into prompts.
        escalation: Auto-escalation thresholds for ``extraction_type="auto"``.
        verification: Zoom-and-verify thresholds.
        schema_shards: Optional number of schema shards for wide schemas.
        llm_kwargs: Extra LiteLLM keyword arguments.
        normalize_output: Preserve source text by default or normalize values.
    """

    def __init__(
        self,
        parser: Any | str | dict | None = "auto",
        ocr: Any | str | None = None,
        model: str = "openai/gpt-4o",
        storage: Any | str | dict | None = None,
        validators: list | None = None,
        review_rules: list | None = None,
        privacy: Any = None,
        extraction_mode: str = "single",
        extraction_type: str = "text",
        n_instances: int = 5,
        temperatures: list[float] | None = None,
        vision_dpi: int = DEFAULT_DPI,
        context: str | None = None,
        escalation: dict | None = None,
        verification: dict | None = None,
        schema_shards: int | None = None,
        llm_kwargs: dict | None = None,
        normalize_output: bool = False,
    ):
        self._parser = parser
        self._ocr = ocr
        self._model = model
        self._storage = storage
        self._validators = validators or []
        self._review_rules = review_rules or []
        self._privacy = privacy
        self._extraction_mode = extraction_mode
        self._extraction_type = extraction_type
        self._n_instances = n_instances
        self._temperatures = temperatures
        self._vision_dpi = vision_dpi
        self._context = context
        self._escalation = escalation
        self._verification = verification
        self._schema_shards = schema_shards
        self._llm_kwargs = llm_kwargs or {}
        self._normalize_output = normalize_output

        parser_type = self._parser
        if isinstance(self._parser, dict):
            parser_type = self._parser.get("type", "auto")

        if (
            self._extraction_type in ("vision", "hybrid")
            and parser_type is not None
            and isinstance(parser_type, str)
            and parser_type not in ("none", "auto")
        ):
            raise ValueError(
                f"extraction_type='{self._extraction_type}' cannot be used with a parser. "
                f"{self._extraction_type.title()} extraction reads the document directly. "
                "Set parser=None, parser='none', or parser='auto'."
            )

        if self._extraction_type in ("vision", "hybrid") and self._privacy is not None:
            raise ValueError(
                f"extraction_type='{self._extraction_type}' cannot be combined with a "
                "privacy policy: vision sends raw page images to the LLM, bypassing "
                "text anonymization. Use extraction_type='text' or 'auto' (auto keeps "
                "the anonymized text path and never escalates when privacy is on)."
            )

    def _resolve_parser(self) -> Any:
        if self._parser is None or self._parser == "none":
            return None
        if isinstance(self._parser, dict):
            return self._resolve_parser_from_dict(self._parser)
        if isinstance(self._parser, str):
            return self._resolve_parser_from_str(self._parser)
        return self._parser

    def _resolve_parser_from_str(self, name: str) -> Any:
        if name == "auto":
            return "auto"
        if name == "pdfplumber":
            from docuflow.parsing.pdfplumber_parser import PdfplumberParser
            return PdfplumberParser()
        if name == "tesseract":
            from docuflow.parsing.tesseract_parser import TesseractParser
            return TesseractParser()
        if name == "docling":
            from docuflow.parsing.docling_parser import DoclingParser
            return DoclingParser()
        if name == "smart":
            from docuflow.parsing.smart_parser import SmartParser
            return SmartParser()
        if name == "azure-di":
            from docuflow.parsing.azure_di import AzureDocumentIntelligenceParser
            return AzureDocumentIntelligenceParser()
        if name == "textract":
            from docuflow.parsing.textract import TextractParser
            return TextractParser()
        if name == "google-docai":
            from docuflow.parsing.google_docai import GoogleDocumentAIParser
            return GoogleDocumentAIParser()
        raise ValueError(f"Unknown parser: {name!r}")

    def _resolve_parser_from_dict(self, cfg: dict) -> Any:
        parser_type = cfg.get("type", "auto")

        if parser_type == "auto":
            return "auto"

        if parser_type == "pdfplumber":
            from docuflow.parsing.pdfplumber_parser import PdfplumberParser
            return PdfplumberParser()

        if parser_type == "tesseract":
            from docuflow.parsing.tesseract_parser import TesseractParser
            kwargs: dict = {}
            if "languages" in cfg:
                kwargs["languages"] = cfg["languages"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            if "preprocess" in cfg:
                kwargs["preprocess_steps"] = cfg["preprocess"]
            return TesseractParser(**kwargs)

        if parser_type == "docling":
            from docuflow.parsing.docling_parser import DoclingParser
            return DoclingParser()

        if parser_type == "smart":
            from docuflow.parsing.smart_parser import SmartParser
            kwargs = {}
            if "languages" in cfg:
                kwargs["ocr_languages"] = cfg["languages"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            if "min_text_length" in cfg:
                kwargs["min_text_length"] = cfg["min_text_length"]
            return SmartParser(**kwargs)

        if parser_type == "azure-di":
            from docuflow.parsing.azure_di import AzureDocumentIntelligenceParser
            kwargs = {}
            if "endpoint" in cfg:
                kwargs["endpoint"] = cfg["endpoint"]
            if "key" in cfg:
                kwargs["key"] = cfg["key"]
            if "model" in cfg:
                kwargs["model"] = cfg["model"]
            return AzureDocumentIntelligenceParser(**kwargs)

        if parser_type == "textract":
            from docuflow.parsing.textract import TextractParser
            kwargs = {}
            if "region" in cfg:
                kwargs["region_name"] = cfg["region"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            return TextractParser(**kwargs)

        if parser_type == "google-docai":
            from docuflow.parsing.google_docai import GoogleDocumentAIParser
            kwargs = {}
            if "project" in cfg:
                kwargs["project"] = cfg["project"]
            if "location" in cfg:
                kwargs["location"] = cfg["location"]
            if "processor_id" in cfg:
                kwargs["processor_id"] = cfg["processor_id"]
            return GoogleDocumentAIParser(**kwargs)

        raise ValueError(f"Unknown parser type: {parser_type!r}")

    def _default_parser_for_source(self, source_kind: SourceKind, *, auto_mode: bool = False) -> Any:
        if source_kind in ("text", "email"):
            return None
        if source_kind == "image":
            from docuflow.parsing.tesseract_parser import TesseractParser

            return TesseractParser()
        if source_kind == "pdf":
            if auto_mode:
                from docuflow.parsing.smart_parser import SmartParser

                return SmartParser()
            from docuflow.parsing.pdfplumber_parser import PdfplumberParser

            return PdfplumberParser()
        if source_kind in ("office", "spreadsheet"):
            from docuflow.parsing.docling_parser import DoclingParser

            return DoclingParser()
        raise ValueError(f"No default parser for source kind: {source_kind!r}")

    def _resolve_parser_for_source(self, source_kind: SourceKind, *, auto_mode: bool = False) -> Any:
        if self._parser is None or self._parser == "none":
            return None

        if isinstance(self._parser, dict):
            parser_type = self._parser.get("type", "auto")
            if parser_type == "auto":
                return self._default_parser_for_source(source_kind, auto_mode=auto_mode)
            return self._resolve_parser_from_dict(self._parser)

        if isinstance(self._parser, str):
            if self._parser == "auto":
                return self._default_parser_for_source(source_kind, auto_mode=auto_mode)
            return self._resolve_parser_from_str(self._parser)

        return self._parser

    def _validate_parserless_source(self, source_kind: SourceKind) -> None:
        if self._extraction_type in ("vision", "hybrid"):
            if source_kind not in ("pdf", "image"):
                raise ValueError(
                    f"extraction_type='{self._extraction_type}' with parser=None supports "
                    "PDF and image inputs. Use extraction_type='text' for text-like files, "
                    "or parser='auto' for parser-backed formats."
                )
            return

        if source_kind not in ("text", "email"):
            raise ValueError(
                "parser=None with text extraction is only supported for text-like inputs. "
                "Use parser='auto' to select an appropriate parser, or use "
                "extraction_type='vision' for PDF/image inputs."
            )

    def _resolve_llm(self) -> Any:
        from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

        kwargs: dict = {"model": self._model}
        if self._llm_kwargs:
            if "max_retries" in self._llm_kwargs:
                kwargs["max_retries"] = self._llm_kwargs["max_retries"]
            if "api_key" in self._llm_kwargs:
                kwargs["api_key"] = self._llm_kwargs["api_key"]
            extra = {
                k: v for k, v in self._llm_kwargs.items()
                if k not in ("max_retries", "api_key")
            }
            kwargs.update(extra)
        return LiteLLMAdapter(**kwargs)

    def _resolve_storage(self) -> Any:
        if self._storage is None:
            return None
        if isinstance(self._storage, dict):
            storage_type = self._storage.get("type", "local")
            if storage_type == "local":
                from docuflow.storage.local import LocalDocumentStore
                path = self._storage.get("path", "./.docuflow_store")
                return LocalDocumentStore(base_path=path)
            raise ValueError(f"Unknown storage type: {storage_type!r}")
        if isinstance(self._storage, str):
            if self._storage == "local":
                from docuflow.storage.local import LocalDocumentStore
                return LocalDocumentStore()
            raise ValueError(f"Unknown storage: {self._storage!r}")
        return self._storage

    async def run(
        self,
        path: str,
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> ExtractionResult:
        """Run the configured pipeline on one document.

        Args:
            path: Input document path.
            schema: Pydantic schema used to validate the extraction.
            **kwargs: Extra metadata forwarded into the pipeline state.

        Returns:
            ExtractionResult: Final extraction result for the document.
        """

        from docuflow.workflow.pipeline import Pipeline
        from docuflow.workflow.steps import (
            Extract,
            ExtractAuto,
            ExtractHybrid,
            ExtractVision,
            Ingest,
            Parse,
            Store,
            Validate,
        )

        llm = self._resolve_llm()
        storage = self._resolve_storage()
        source_kind = detect_source_kind(Path(path))

        steps: list = [Ingest(path=path)]

        if self._extraction_type == "vision":
            if source_kind not in ("pdf", "image"):
                raise ValueError(
                    "Vision extraction currently supports PDF and image inputs. "
                    "Use extraction_type='text' with parser='auto' for text and office files."
                )
            if self._privacy:
                from docuflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                ExtractVision(
                    schema=schema, llm=llm,
                    mode=self._extraction_mode,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    dpi=self._vision_dpi,
                    context=self._context,
                    normalize_output=self._normalize_output,
                )
            )
        elif self._extraction_type == "hybrid":
            if source_kind not in ("pdf", "image"):
                raise ValueError(
                    "Hybrid extraction currently supports PDF and image inputs. "
                    "Use extraction_type='text' with parser='auto' for text and office files."
                )
            if self._privacy:
                from docuflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                ExtractHybrid(
                    schema=schema, llm=llm,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    dpi=self._vision_dpi,
                    context=self._context,
                    normalize_output=self._normalize_output,
                )
            )
        elif self._extraction_type == "auto":
            from docuflow.extraction.escalation import EscalationPolicy

            parser = self._resolve_parser_for_source(source_kind, auto_mode=True)
            if parser is None and self._parser in (None, "none"):
                self._validate_parserless_source(source_kind)
            if parser is not None:
                steps.append(Parse(parser=parser))
            if self._privacy:
                from docuflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))

            if parser is None:
                steps.append(
                    Extract(
                        schema=schema, llm=llm,
                        mode=self._extraction_mode,
                        n_instances=self._n_instances,
                        temperatures=self._temperatures,
                        context=self._context,
                        schema_shards=self._schema_shards,
                        normalize_output=self._normalize_output,
                    )
                )
            else:
                steps.append(
                    ExtractAuto(
                        schema=schema, llm=llm,
                        mode=self._extraction_mode,
                        n_instances=self._n_instances,
                        temperatures=self._temperatures,
                        dpi=self._vision_dpi,
                        context=self._context,
                        policy=EscalationPolicy(**(self._escalation or {})),
                        # Vision sends raw page images to the LLM, bypassing
                        # anonymization — never escalate when privacy is on.
                        allow_escalation=self._privacy is None and source_kind in ("pdf", "image"),
                        normalize_output=self._normalize_output,
                    )
                )
        else:
            parser = self._resolve_parser_for_source(source_kind)
            if parser is None and self._parser in (None, "none"):
                self._validate_parserless_source(source_kind)
            if parser is not None:
                steps.append(Parse(parser=parser))
            if self._privacy:
                from docuflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                Extract(
                    schema=schema, llm=llm,
                    mode=self._extraction_mode,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    context=self._context,
                    schema_shards=self._schema_shards,
                    normalize_output=self._normalize_output,
                )
            )

        if self._verification is not None:
            from docuflow.extraction.verify import VerificationPolicy
            from docuflow.workflow.steps import VerifyFields

            steps.append(
                VerifyFields(
                    schema=schema, llm=llm,
                    policy=VerificationPolicy(**self._verification),
                )
            )

        if self._validators:
            steps.append(Validate(validators=self._validators))

        if self._review_rules:
            from docuflow.workflow.steps import Review

            steps.append(Review(rules=self._review_rules))

        if storage:
            steps.append(Store(storage=storage))

        pipeline = Pipeline(steps=steps)
        result = await pipeline.run()

        if not result.success:
            from docuflow.errors import WorkflowError

            raise WorkflowError(
                f"Pipeline failed: {'; '.join(result.errors)}",
                result=result,
            )

        extraction_result = result.state.extraction_result
        extraction_result.trace = result.trace
        if result.state.document is not None:
            extraction_result.raw_text = result.state.document.raw_text
        return extraction_result

    def run_sync(
        self,
        path: str,
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> ExtractionResult:
        """Synchronous wrapper for :meth:`run`."""

        return run_sync(self.run(path, schema, **kwargs))

    def export(
        self,
        schema: type[BaseModel],
        name: str = "workflow",
        version: str = "1.0",
        description: str = "",
    ) -> dict[str, Any]:
        from docuflow.workflow_config import export_config

        return export_config(self, schema, name, version, description)

    def export_yaml(
        self,
        schema: type[BaseModel],
        name: str = "workflow",
        version: str = "1.0",
        description: str = "",
    ) -> str:
        from docuflow.workflow_config import export_yaml

        return export_yaml(self, schema, name, version, description)
