"""Portable workflow configuration — YAML-driven document processing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

from docflow.extraction.models import ExtractionResult
from docflow.templates.loader import yaml_to_pydantic

if TYPE_CHECKING:
    from docflow.processor import DocumentPipeline


# ---------------------------------------------------------------------------
# WorkflowConfig — the portable artifact
# ---------------------------------------------------------------------------


class WorkflowConfig(BaseModel):
    name: str = "workflow"
    version: str = "1.0"
    description: str = ""

    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")

    parser: str | dict[str, Any] = "pdfplumber"
    model: str = "openai/gpt-4o"
    extraction_type: str = "text"
    extraction_mode: str = "single"
    escalation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    n_instances: int = 5
    temperatures: list[float] | None = None
    vision_dpi: int | None = None
    scoring: str = "qualitative"
    context: str | None = None

    validation: list[dict[str, Any]] = Field(default_factory=list)
    review: list[dict[str, Any]] = Field(default_factory=list)

    privacy: dict[str, Any] | None = None
    storage: str | dict[str, Any] | None = None
    llm: dict[str, Any] | None = None
    quality_threshold: float = 0.7

    model_config = {"populate_by_name": True}

    @property
    def parser_type(self) -> str:
        if isinstance(self.parser, dict):
            return self.parser.get("type", "pdfplumber")
        return self.parser

    def build_schema(self) -> type[BaseModel]:
        return yaml_to_pydantic({"name": self.name, "fields": self.schema_})

    def build_validators(self) -> list:
        from docflow.validation import EvidenceRequired, RequiredFields

        validators = []
        for rule in self.validation:
            if "required_fields" in rule:
                validators.append(RequiredFields(rule["required_fields"]))
            elif "evidence_required" in rule:
                validators.append(EvidenceRequired(rule["evidence_required"]))
            elif "type_validation" in rule:
                from docflow.validation import TypeValidation
                validators.append(TypeValidation())
        return validators

    def build_review_rules(self) -> list:
        from docflow.review import (
            AnyFieldConfidenceBelow,
            FieldConfidenceBelow,
            FieldMissing,
            HasValidationErrors,
            NoEvidence,
            OverallConfidenceBelow,
        )

        rules = []
        for rule in self.review:
            if "overall_confidence_below" in rule:
                rules.append(OverallConfidenceBelow(rule["overall_confidence_below"]))
            elif "field_confidence_below" in rule:
                rules.append(FieldConfidenceBelow(rule["field_confidence_below"]))
            elif "any_field_confidence_below" in rule:
                rules.append(AnyFieldConfidenceBelow(rule["any_field_confidence_below"]))
            elif "has_validation_errors" in rule:
                rules.append(HasValidationErrors())
            elif "field_missing" in rule:
                rules.append(FieldMissing(rule["field_missing"]))
            elif "no_evidence" in rule:
                fields = rule["no_evidence"]
                rules.append(NoEvidence(fields if fields is not True else None))
            elif "llm_reviewer" in rule:
                from docflow.extraction.llm.litellm_adapter import LiteLLMAdapter
                from docflow.review import LLMReviewer
                cfg = rule["llm_reviewer"]
                llm_model = cfg.get("model", self.model)
                rules.append(LLMReviewer(
                    name=cfg["name"],
                    prompt=cfg["prompt"],
                    llm=LiteLLMAdapter(model=llm_model),
                ))
        return rules

    def build_privacy(self) -> Any:
        if not self.privacy:
            return None
        from docflow.privacy.models import AnonymizationMode
        from docflow.privacy.policy import PrivacyPolicy
        cfg = dict(self.privacy)
        if "mode" in cfg:
            cfg["mode"] = AnonymizationMode(cfg["mode"])
        provider_cfg = cfg.get("provider")
        if provider_cfg == "presidio" or isinstance(provider_cfg, dict):
            from docflow.privacy.presidio_provider import PresidioProvider
            if isinstance(provider_cfg, dict):
                cfg["provider"] = PresidioProvider(
                    language=provider_cfg.get("language", "en"),
                    model=provider_cfg.get("model"),
                )
            else:
                lang = cfg.pop("language", "en")
                cfg["provider"] = PresidioProvider(language=lang)
        if "mapping_store" in cfg:
            ms = cfg["mapping_store"]
            if isinstance(ms, dict):
                from docflow.privacy.mapping_store import LocalMappingStore
                cfg["mapping_store"] = LocalMappingStore(ms.get("path", "./.docflow_mappings"))
            elif isinstance(ms, str):
                from docflow.privacy.mapping_store import LocalMappingStore
                cfg["mapping_store"] = LocalMappingStore(ms)
        return PrivacyPolicy(**cfg)

    def _build_parser_config(self) -> str | dict[str, Any]:
        """Return a parser string or config dict for DocumentPipeline."""
        if isinstance(self.parser, str):
            return self.parser
        return dict(self.parser)

    def _build_storage_config(self) -> str | dict[str, Any] | None:
        if self.storage is None:
            return None
        if isinstance(self.storage, str):
            return self.storage
        return dict(self.storage)

    def _build_llm_kwargs(self) -> dict[str, Any]:
        if not self.llm:
            return {}
        return dict(self.llm)

    def build_pipeline(self) -> "DocumentPipeline":
        from docflow.processor import DocumentPipeline

        kwargs: dict[str, Any] = {
            "parser": self._build_parser_config(),
            "model": self.model,
            "extraction_type": self.extraction_type,
            "extraction_mode": self.extraction_mode,
            "escalation": self.escalation,
            "verification": self.verification,
            "n_instances": self.n_instances,
            "scoring": self.scoring,
            "validators": self.build_validators() or None,
            "review_rules": self.build_review_rules() or None,
        }
        if self.temperatures is not None:
            kwargs["temperatures"] = self.temperatures
        if self.vision_dpi is not None:
            kwargs["vision_dpi"] = self.vision_dpi
        if self.context is not None:
            kwargs["context"] = self.context

        privacy = self.build_privacy()
        if privacy is not None:
            kwargs["privacy"] = privacy

        storage = self._build_storage_config()
        if storage is not None:
            kwargs["storage"] = storage

        llm_kwargs = self._build_llm_kwargs()
        if llm_kwargs:
            kwargs["llm_kwargs"] = llm_kwargs

        return DocumentPipeline(**kwargs)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_workflow_config(source: str | Path | dict) -> WorkflowConfig:
    if isinstance(source, dict):
        return WorkflowConfig.model_validate(source)
    path = Path(source)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return WorkflowConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


async def run_workflow(
    config: str | Path | dict | WorkflowConfig,
    path: str,
) -> ExtractionResult:
    if not isinstance(config, WorkflowConfig):
        config = load_workflow_config(config)
    pipeline = config.build_pipeline()
    schema = config.build_schema()
    return await pipeline.run(path, schema)


def run_workflow_sync(
    config: str | Path | dict | WorkflowConfig,
    path: str,
) -> ExtractionResult:
    if not isinstance(config, WorkflowConfig):
        config = load_workflow_config(config)
    pipeline = config.build_pipeline()
    schema = config.build_schema()
    return pipeline.run_sync(path, schema)


# ---------------------------------------------------------------------------
# Exporting — pipeline config → YAML dict / string
# ---------------------------------------------------------------------------

_TYPE_REVERSE: dict[type, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
}


def _schema_to_fields(schema: type[BaseModel]) -> dict[str, Any]:
    import types

    fields: dict[str, Any] = {}
    for name, field_info in schema.model_fields.items():
        annotation = field_info.annotation

        raw_type = annotation
        if isinstance(annotation, types.UnionType):
            args = [a for a in annotation.__args__ if a is not type(None)]
            if args:
                raw_type = args[0]

        type_str = _TYPE_REVERSE.get(raw_type, "str")

        entry: dict[str, Any] = {"type": type_str}

        if field_info.is_required():
            entry["required"] = True

        if field_info.default is not None and not field_info.is_required():
            entry["default"] = field_info.default

        desc = field_info.description
        if desc:
            entry["description"] = desc

        fields[name] = entry
    return fields


def _validators_to_list(validators: list) -> list[dict[str, Any]]:
    from docflow.validation import EvidenceRequired, RequiredFields

    result = []
    for v in validators:
        if isinstance(v, RequiredFields):
            result.append({"required_fields": v.fields})
        elif isinstance(v, EvidenceRequired):
            result.append({"evidence_required": v.fields})
    return result


def _review_rules_to_list(rules: list) -> list[dict[str, Any]]:
    from docflow.review import (
        AnyFieldConfidenceBelow,
        FieldConfidenceBelow,
        FieldMissing,
        HasValidationErrors,
        NoEvidence,
        OverallConfidenceBelow,
    )

    result = []
    for r in rules:
        if isinstance(r, OverallConfidenceBelow):
            result.append({"overall_confidence_below": r.threshold})
        elif isinstance(r, FieldConfidenceBelow):
            result.append({"field_confidence_below": r.fields})
        elif isinstance(r, AnyFieldConfidenceBelow):
            result.append({"any_field_confidence_below": r.threshold})
        elif isinstance(r, HasValidationErrors):
            result.append({"has_validation_errors": True})
        elif isinstance(r, FieldMissing):
            result.append({"field_missing": r.fields})
        elif isinstance(r, NoEvidence):
            result.append({"no_evidence": r.fields if r.fields else True})
    return result


def _export_parser(pipeline: Any) -> str | dict[str, Any]:
    parser = pipeline._parser
    if isinstance(parser, str):
        return parser
    if isinstance(parser, dict):
        return dict(parser)
    name = type(parser).__name__
    if "Pdfplumber" in name:
        return "pdfplumber"
    if "Tesseract" in name and "Smart" not in name:
        cfg: dict[str, Any] = {"type": "tesseract"}
        if hasattr(parser, "languages") and parser.languages != ["eng"]:
            cfg["languages"] = parser.languages
        if hasattr(parser, "dpi") and parser.dpi != 200:
            cfg["dpi"] = parser.dpi
        if hasattr(parser, "preprocess_steps") and parser.preprocess_steps:
            cfg["preprocess"] = parser.preprocess_steps
        return cfg if len(cfg) > 1 else "tesseract"
    if "Smart" in name:
        cfg = {"type": "smart"}
        if hasattr(parser, "ocr_languages") and parser.ocr_languages != ["eng"]:
            cfg["languages"] = parser.ocr_languages
        if hasattr(parser, "dpi") and parser.dpi != 200:
            cfg["dpi"] = parser.dpi
        if hasattr(parser, "min_text_length") and parser.min_text_length != 20:
            cfg["min_text_length"] = parser.min_text_length
        return cfg if len(cfg) > 1 else "smart"
    if "Docling" in name:
        return "docling"
    if "AzureDocumentIntelligence" in name:
        cfg = {"type": "azure-di"}
        if hasattr(parser, "model") and parser.model != "prebuilt-read":
            cfg["model"] = parser.model
        return cfg if len(cfg) > 1 else "azure-di"
    if "Textract" in name:
        cfg = {"type": "textract"}
        if hasattr(parser, "region_name") and parser.region_name:
            cfg["region"] = parser.region_name
        if hasattr(parser, "dpi") and parser.dpi != 200:
            cfg["dpi"] = parser.dpi
        return cfg if len(cfg) > 1 else "textract"
    if "GoogleDocumentAI" in name:
        return "google-docai"
    return "pdfplumber"


def export_config(
    pipeline: Any,
    schema: type[BaseModel],
    name: str = "workflow",
    version: str = "1.0",
    description: str = "",
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": name,
        "version": version,
    }
    if description:
        config["description"] = description

    config["schema"] = _schema_to_fields(schema)
    config["parser"] = _export_parser(pipeline)
    config["model"] = pipeline._model
    config["extraction_type"] = pipeline._extraction_type
    config["extraction_mode"] = pipeline._extraction_mode
    if getattr(pipeline, "_escalation", None):
        config["escalation"] = dict(pipeline._escalation)
    if getattr(pipeline, "_verification", None):
        config["verification"] = dict(pipeline._verification)
    config["n_instances"] = pipeline._n_instances
    config["scoring"] = pipeline._scoring

    if pipeline._temperatures:
        config["temperatures"] = pipeline._temperatures
    if pipeline._context:
        config["context"] = pipeline._context

    validators = _validators_to_list(pipeline._validators)
    if validators:
        config["validation"] = validators

    review_rules = _review_rules_to_list(pipeline._review_rules)
    if review_rules:
        config["review"] = review_rules

    if pipeline._llm_kwargs:
        config["llm"] = dict(pipeline._llm_kwargs)

    if pipeline._storage is not None:
        if isinstance(pipeline._storage, dict):
            config["storage"] = dict(pipeline._storage)
        elif isinstance(pipeline._storage, str):
            config["storage"] = pipeline._storage
        elif hasattr(pipeline._storage, "base_path"):
            config["storage"] = {"type": "local", "path": str(pipeline._storage.base_path)}

    return config


def export_yaml(
    pipeline: Any,
    schema: type[BaseModel],
    name: str = "workflow",
    version: str = "1.0",
    description: str = "",
) -> str:
    config = export_config(pipeline, schema, name, version, description)
    return yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
