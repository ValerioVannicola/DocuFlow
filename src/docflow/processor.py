from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from docflow._sync import run_sync
from docflow.constants import DEFAULT_DPI
from docflow.extraction.models import ExtractionResult


class DocumentPipeline:
    def __init__(
        self,
        parser: Any | str | dict | None = "pdfplumber",
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
        scoring: str = "qualitative",
        escalation: dict | None = None,
        llm_kwargs: dict | None = None,
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
        self._scoring = scoring
        self._escalation = escalation
        self._llm_kwargs = llm_kwargs or {}

        parser_type = self._parser
        if isinstance(self._parser, dict):
            parser_type = self._parser.get("type", "pdfplumber")

        if (
            self._extraction_type in ("vision", "hybrid")
            and parser_type is not None
            and isinstance(parser_type, str)
            and parser_type != "none"
        ):
                raise ValueError(
                    f"extraction_type='{self._extraction_type}' cannot be used with a parser. "
                    f"{self._extraction_type.title()} extraction reads the PDF directly. "
                    "Set parser=None or parser='none'."
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
        if name == "pdfplumber":
            from docflow.parsing.pdfplumber_parser import PdfplumberParser
            return PdfplumberParser()
        if name == "tesseract":
            from docflow.parsing.tesseract_parser import TesseractParser
            return TesseractParser()
        if name == "docling":
            from docflow.parsing.docling_parser import DoclingParser
            return DoclingParser()
        if name == "smart":
            from docflow.parsing.smart_parser import SmartParser
            return SmartParser()
        if name == "azure-di":
            from docflow.parsing.azure_di import AzureDocumentIntelligenceParser
            return AzureDocumentIntelligenceParser()
        if name == "textract":
            from docflow.parsing.textract import TextractParser
            return TextractParser()
        if name == "google-docai":
            from docflow.parsing.google_docai import GoogleDocumentAIParser
            return GoogleDocumentAIParser()
        raise ValueError(f"Unknown parser: {name!r}")

    def _resolve_parser_from_dict(self, cfg: dict) -> Any:
        parser_type = cfg.get("type", "pdfplumber")

        if parser_type == "pdfplumber":
            from docflow.parsing.pdfplumber_parser import PdfplumberParser
            return PdfplumberParser()

        if parser_type == "tesseract":
            from docflow.parsing.tesseract_parser import TesseractParser
            kwargs: dict = {}
            if "languages" in cfg:
                kwargs["languages"] = cfg["languages"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            if "preprocess" in cfg:
                kwargs["preprocess_steps"] = cfg["preprocess"]
            return TesseractParser(**kwargs)

        if parser_type == "docling":
            from docflow.parsing.docling_parser import DoclingParser
            return DoclingParser()

        if parser_type == "smart":
            from docflow.parsing.smart_parser import SmartParser
            kwargs = {}
            if "languages" in cfg:
                kwargs["ocr_languages"] = cfg["languages"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            if "min_text_length" in cfg:
                kwargs["min_text_length"] = cfg["min_text_length"]
            return SmartParser(**kwargs)

        if parser_type == "azure-di":
            from docflow.parsing.azure_di import AzureDocumentIntelligenceParser
            kwargs = {}
            if "endpoint" in cfg:
                kwargs["endpoint"] = cfg["endpoint"]
            if "key" in cfg:
                kwargs["key"] = cfg["key"]
            if "model" in cfg:
                kwargs["model"] = cfg["model"]
            return AzureDocumentIntelligenceParser(**kwargs)

        if parser_type == "textract":
            from docflow.parsing.textract import TextractParser
            kwargs = {}
            if "region" in cfg:
                kwargs["region_name"] = cfg["region"]
            if "dpi" in cfg:
                kwargs["dpi"] = cfg["dpi"]
            return TextractParser(**kwargs)

        if parser_type == "google-docai":
            from docflow.parsing.google_docai import GoogleDocumentAIParser
            kwargs = {}
            if "project" in cfg:
                kwargs["project"] = cfg["project"]
            if "location" in cfg:
                kwargs["location"] = cfg["location"]
            if "processor_id" in cfg:
                kwargs["processor_id"] = cfg["processor_id"]
            return GoogleDocumentAIParser(**kwargs)

        raise ValueError(f"Unknown parser type: {parser_type!r}")

    def _resolve_llm(self) -> Any:
        from docflow.extraction.llm.litellm_adapter import LiteLLMAdapter

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
                from docflow.storage.local import LocalDocumentStore
                path = self._storage.get("path", "./.docflow_store")
                return LocalDocumentStore(base_path=path)
            raise ValueError(f"Unknown storage type: {storage_type!r}")
        if isinstance(self._storage, str):
            if self._storage == "local":
                from docflow.storage.local import LocalDocumentStore
                return LocalDocumentStore()
            raise ValueError(f"Unknown storage: {self._storage!r}")
        return self._storage

    async def run(
        self,
        path: str,
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> ExtractionResult:
        from docflow.workflow.pipeline import Pipeline
        from docflow.workflow.steps import (
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

        steps: list = [Ingest(path=path)]

        if self._extraction_type == "vision":
            if self._privacy:
                from docflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                ExtractVision(
                    schema=schema, llm=llm,
                    mode=self._extraction_mode,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    dpi=self._vision_dpi,
                    context=self._context,
                    scoring=self._scoring,
                )
            )
        elif self._extraction_type == "hybrid":
            if self._privacy:
                from docflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                ExtractHybrid(
                    schema=schema, llm=llm,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    dpi=self._vision_dpi,
                    context=self._context,
                    scoring=self._scoring,
                )
            )
        elif self._extraction_type == "auto":
            from docflow.extraction.escalation import EscalationPolicy

            # Auto mode needs an OCR-capable parser to judge OCR quality;
            # upgrade the bare default to the smart parser.
            parser_cfg = self._parser
            if parser_cfg in (None, "none", "pdfplumber"):
                parser_cfg = "smart"
            saved_parser = self._parser
            self._parser = parser_cfg
            try:
                parser = self._resolve_parser()
            finally:
                self._parser = saved_parser
            steps.append(Parse(parser=parser))
            if self._privacy:
                from docflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                ExtractAuto(
                    schema=schema, llm=llm,
                    mode=self._extraction_mode,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    dpi=self._vision_dpi,
                    context=self._context,
                    scoring=self._scoring,
                    policy=EscalationPolicy(**(self._escalation or {})),
                    # Vision sends raw page images to the LLM, bypassing
                    # anonymization — never escalate when privacy is on.
                    allow_escalation=self._privacy is None,
                )
            )
        else:
            parser = self._resolve_parser()
            steps.append(Parse(parser=parser))
            if self._privacy:
                from docflow.workflow.steps import Anonymize

                steps.append(Anonymize(policy=self._privacy))
            steps.append(
                Extract(
                    schema=schema, llm=llm,
                    mode=self._extraction_mode,
                    n_instances=self._n_instances,
                    temperatures=self._temperatures,
                    context=self._context,
                    scoring=self._scoring,
                )
            )

        if self._validators:
            steps.append(Validate(validators=self._validators))

        if self._review_rules:
            from docflow.workflow.steps import Review

            steps.append(Review(rules=self._review_rules))

        if storage:
            steps.append(Store(storage=storage))

        pipeline = Pipeline(steps=steps)
        result = await pipeline.run()

        if not result.success:
            from docflow.errors import WorkflowError

            raise WorkflowError(
                f"Pipeline failed: {'; '.join(result.errors)}",
                result=result,
            )

        return result.state.extraction_result

    def run_sync(
        self,
        path: str,
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> ExtractionResult:
        return run_sync(self.run(path, schema, **kwargs))

    def export(
        self,
        schema: type[BaseModel],
        name: str = "workflow",
        version: str = "1.0",
        description: str = "",
    ) -> dict[str, Any]:
        from docflow.workflow_config import export_config

        return export_config(self, schema, name, version, description)

    def export_yaml(
        self,
        schema: type[BaseModel],
        name: str = "workflow",
        version: str = "1.0",
        description: str = "",
    ) -> str:
        from docflow.workflow_config import export_yaml

        return export_yaml(self, schema, name, version, description)
