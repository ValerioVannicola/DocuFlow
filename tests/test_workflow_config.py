from __future__ import annotations

import pytest
import yaml

from docuflow.processor import DocumentPipeline
from docuflow.review import (
    AnyFieldConfidenceBelow,
    FieldConfidenceBelow,
    FieldMissing,
    HasValidationErrors,
    NoEvidence,
    OverallConfidenceBelow,
)
from docuflow.validation import EvidenceRequired, RequiredFields
from docuflow.workflow_config import (
    export_config,
    export_yaml,
    load_workflow_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_YAML = {
    "name": "invoice",
    "schema": {
        "supplier_name": {"type": "str", "required": True, "description": "Supplier"},
        "total": {"type": "float", "required": True, "description": "Total amount"},
    },
}

FULL_YAML = {
    "name": "invoice-extraction",
    "version": "2.0",
    "description": "Full invoice workflow",
    "schema": {
        "supplier_name": {"type": "str", "required": True, "description": "Supplier"},
        "invoice_number": {"type": "str", "description": "Invoice ref"},
        "total": {"type": "float", "required": True, "description": "Total"},
        "currency": {"type": "str", "default": "EUR", "description": "Currency"},
    },
    "parser": "smart",
    "model": "openai/gpt-4o-mini",
    "extraction_type": "text",
    "extraction_mode": "multi",
    "n_instances": 3,
    "context": "You are processing pharmaceutical invoices.",
    "validation": [
        {"required_fields": ["supplier_name", "total"]},
        {"evidence_required": ["total"]},
    ],
    "review": [
        {"overall_confidence_below": 0.7},
        {"field_missing": ["total", "invoice_number"]},
    ],
    "quality_threshold": 0.85,
}


# ---------------------------------------------------------------------------
# WorkflowConfig — loading
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_load_from_dict_minimal(self):
        cfg = load_workflow_config(MINIMAL_YAML)
        assert cfg.name == "invoice"
        assert "supplier_name" in cfg.schema_
        assert cfg.parser == "auto"
        assert cfg.model == "openai/gpt-4o"

    def test_load_from_dict_full(self):
        cfg = load_workflow_config(FULL_YAML)
        assert cfg.name == "invoice-extraction"
        assert cfg.version == "2.0"
        assert cfg.parser == "smart"
        assert cfg.model == "openai/gpt-4o-mini"
        assert cfg.extraction_mode == "multi"
        assert cfg.n_instances == 3
        assert cfg.context == "You are processing pharmaceutical invoices."
        assert len(cfg.validation) == 2
        assert len(cfg.review) == 2
        assert cfg.quality_threshold == 0.85

    def test_load_from_yaml_file(self, tmp_path):
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(yaml.dump(FULL_YAML), encoding="utf-8")

        cfg = load_workflow_config(yaml_path)
        assert cfg.name == "invoice-extraction"
        assert cfg.model == "openai/gpt-4o-mini"

    def test_load_from_string_path(self, tmp_path):
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(yaml.dump(MINIMAL_YAML), encoding="utf-8")

        cfg = load_workflow_config(str(yaml_path))
        assert cfg.name == "invoice"

    def test_defaults(self):
        cfg = load_workflow_config({"schema": {"a": {"type": "str"}}})
        assert cfg.name == "workflow"
        assert cfg.version == "1.0"
        assert cfg.parser == "auto"
        assert cfg.extraction_mode == "single"
        assert cfg.quality_threshold == 0.7


# ---------------------------------------------------------------------------
# Schema building
# ---------------------------------------------------------------------------


class TestBuildSchema:
    def test_builds_pydantic_model(self):
        cfg = load_workflow_config(FULL_YAML)
        schema = cfg.build_schema()

        assert schema.__name__ == "Invoice-extraction"
        fields = schema.model_fields
        assert "supplier_name" in fields
        assert "total" in fields
        assert "currency" in fields

    def test_schema_defaults(self):
        cfg = load_workflow_config(FULL_YAML)
        schema = cfg.build_schema()

        currency_field = schema.model_fields["currency"]
        assert currency_field.default == "EUR"

    def test_schema_types(self):
        cfg = load_workflow_config(FULL_YAML)
        schema = cfg.build_schema()

        instance = schema(supplier_name="Acme", total=100.0)
        assert isinstance(instance.total, float)
        assert isinstance(instance.supplier_name, str)

    def test_minimal_schema(self):
        cfg = load_workflow_config({"schema": {"name": {"type": "str"}}})
        schema = cfg.build_schema()
        assert "name" in schema.model_fields


# ---------------------------------------------------------------------------
# Validator building
# ---------------------------------------------------------------------------


class TestBuildValidators:
    def test_required_fields(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "validation": [{"required_fields": ["a", "b"]}],
        })
        validators = cfg.build_validators()
        assert len(validators) == 1
        assert isinstance(validators[0], RequiredFields)
        assert validators[0].fields == ["a", "b"]

    def test_evidence_required(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "validation": [{"evidence_required": ["total"]}],
        })
        validators = cfg.build_validators()
        assert len(validators) == 1
        assert isinstance(validators[0], EvidenceRequired)
        assert validators[0].fields == ["total"]

    def test_multiple_validators(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "validation": [
                {"required_fields": ["a"]},
                {"evidence_required": ["a"]},
            ],
        })
        validators = cfg.build_validators()
        assert len(validators) == 2

    def test_empty_validation(self):
        cfg = load_workflow_config({"schema": {"a": {"type": "str"}}})
        assert cfg.build_validators() == []


# ---------------------------------------------------------------------------
# Review rule building
# ---------------------------------------------------------------------------


class TestBuildReviewRules:
    def test_overall_confidence_below(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"overall_confidence_below": 0.8}],
        })
        rules = cfg.build_review_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], OverallConfidenceBelow)
        assert rules[0].threshold == 0.8

    def test_field_confidence_below(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"field_confidence_below": {"total": 0.9}}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], FieldConfidenceBelow)
        assert rules[0].fields == {"total": 0.9}

    def test_any_field_confidence_below(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"any_field_confidence_below": 0.5}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], AnyFieldConfidenceBelow)
        assert rules[0].threshold == 0.5

    def test_has_validation_errors(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"has_validation_errors": True}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], HasValidationErrors)

    def test_field_missing(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"field_missing": ["total"]}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], FieldMissing)
        assert rules[0].fields == ["total"]

    def test_no_evidence(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"no_evidence": ["total"]}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], NoEvidence)
        assert rules[0].fields == ["total"]

    def test_no_evidence_all_fields(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "review": [{"no_evidence": True}],
        })
        rules = cfg.build_review_rules()
        assert isinstance(rules[0], NoEvidence)
        assert rules[0].fields is None

    def test_multiple_rules(self):
        cfg = load_workflow_config(FULL_YAML)
        rules = cfg.build_review_rules()
        assert len(rules) == 2

    def test_empty_review(self):
        cfg = load_workflow_config({"schema": {"a": {"type": "str"}}})
        assert cfg.build_review_rules() == []


# ---------------------------------------------------------------------------
# Pipeline building
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    def test_builds_document_pipeline(self):
        cfg = load_workflow_config(FULL_YAML)
        pipeline = cfg.build_pipeline()

        assert isinstance(pipeline, DocumentPipeline)
        assert pipeline._model == "openai/gpt-4o-mini"
        assert pipeline._parser == "smart"
        assert pipeline._extraction_mode == "multi"
        assert pipeline._n_instances == 3
        assert pipeline._context == "You are processing pharmaceutical invoices."
        assert pipeline._normalize_output is False
        assert len(pipeline._validators) == 2
        assert len(pipeline._review_rules) == 2

    def test_minimal_pipeline(self):
        cfg = load_workflow_config(MINIMAL_YAML)
        pipeline = cfg.build_pipeline()

        assert isinstance(pipeline, DocumentPipeline)
        assert pipeline._parser == "auto"
        assert pipeline._model == "openai/gpt-4o"
        assert pipeline._validators == []
        assert pipeline._review_rules == []


# ---------------------------------------------------------------------------
# Export — pipeline → config dict → YAML
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_config_basic(self):
        from pydantic import BaseModel, Field

        class Invoice(BaseModel):
            supplier: str = Field(description="Supplier name")
            total: float = Field(description="Total amount")

        pipeline = DocumentPipeline(
            parser="smart",
            model="openai/gpt-4o-mini",
            normalize_output=True,
        )
        config = export_config(pipeline, Invoice, name="invoice", version="1.0")

        assert config["name"] == "invoice"
        assert config["parser"] == "smart"
        assert config["model"] == "openai/gpt-4o-mini"
        assert config["normalize_output"] is True
        assert "supplier" in config["schema"]
        assert "total" in config["schema"]
        assert config["schema"]["supplier"]["type"] == "str"
        assert config["schema"]["total"]["type"] == "float"

    def test_export_with_validators_and_rules(self):
        from pydantic import BaseModel

        class S(BaseModel):
            a: str

        pipeline = DocumentPipeline(
            validators=[RequiredFields(["a"]), EvidenceRequired(["a"])],
            review_rules=[OverallConfidenceBelow(0.8), FieldMissing(["a"])],
        )
        config = export_config(pipeline, S)

        assert len(config["validation"]) == 2
        assert config["validation"][0] == {"required_fields": ["a"]}
        assert config["validation"][1] == {"evidence_required": ["a"]}
        assert len(config["review"]) == 2
        assert config["review"][0] == {"overall_confidence_below": 0.8}
        assert config["review"][1] == {"field_missing": ["a"]}

    def test_export_yaml_string(self):
        from pydantic import BaseModel

        class S(BaseModel):
            name: str

        pipeline = DocumentPipeline()
        yaml_str = export_yaml(pipeline, S, name="test")

        assert isinstance(yaml_str, str)
        data = yaml.safe_load(yaml_str)
        assert data["name"] == "test"
        assert "name" in data["schema"]

    def test_pipeline_export_method(self):
        from pydantic import BaseModel

        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline(model="openai/gpt-4o-mini")
        config = pipeline.export(S, name="my-workflow")

        assert config["name"] == "my-workflow"
        assert config["model"] == "openai/gpt-4o-mini"

    def test_pipeline_export_yaml_method(self):
        from pydantic import BaseModel

        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline()
        yaml_str = pipeline.export_yaml(S)

        assert isinstance(yaml_str, str)
        parsed = yaml.safe_load(yaml_str)
        assert "schema" in parsed

    def test_export_context(self):
        from pydantic import BaseModel

        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline(context="You are a lawyer.")
        config = export_config(pipeline, S)
        assert config["context"] == "You are a lawyer."

    def test_export_no_context_omitted(self):
        from pydantic import BaseModel

        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline()
        config = export_config(pipeline, S)
        assert "context" not in config


# ---------------------------------------------------------------------------
# Roundtrip — export → load → same config
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_export_load_roundtrip(self):
        from pydantic import BaseModel, Field

        class Invoice(BaseModel):
            supplier: str = Field(description="Supplier name")
            total: float = Field(description="Total amount")

        pipeline = DocumentPipeline(
            parser="smart",
            model="openai/gpt-4o-mini",
            extraction_mode="multi",
            n_instances=3,
            context="pharma invoices",
            validators=[RequiredFields(["supplier", "total"])],
            review_rules=[OverallConfidenceBelow(0.8)],
        )

        config_dict = pipeline.export(Invoice, name="invoice", version="2.0")
        cfg = load_workflow_config(config_dict)

        assert cfg.name == "invoice"
        assert cfg.version == "2.0"
        assert cfg.parser == "smart"
        assert cfg.model == "openai/gpt-4o-mini"
        assert cfg.extraction_mode == "multi"
        assert cfg.n_instances == 3
        assert cfg.context == "pharma invoices"
        assert len(cfg.validation) == 1
        assert len(cfg.review) == 1

        rebuilt_pipeline = cfg.build_pipeline()
        assert rebuilt_pipeline._parser == "smart"
        assert rebuilt_pipeline._model == "openai/gpt-4o-mini"
        assert rebuilt_pipeline._extraction_mode == "multi"

    def test_yaml_file_roundtrip(self, tmp_path):
        from pydantic import BaseModel, Field

        class Receipt(BaseModel):
            store: str = Field(description="Store name")
            amount: float = Field(description="Total")

        pipeline = DocumentPipeline(
            parser="tesseract",
            model="openai/gpt-4o",
            validators=[RequiredFields(["store"])],
            normalize_output=True,
        )

        yaml_str = pipeline.export_yaml(Receipt, name="receipt")
        yaml_path = tmp_path / "receipt.yaml"
        yaml_path.write_text(yaml_str, encoding="utf-8")

        cfg = load_workflow_config(yaml_path)
        assert cfg.name == "receipt"
        assert cfg.parser == "tesseract"
        assert cfg.normalize_output is True
        assert cfg.build_validators()[0].fields == ["store"]


# ---------------------------------------------------------------------------
# CLI — docuflow run
# ---------------------------------------------------------------------------


class TestCLI:
    def test_run_command_exists(self):
        from click.testing import CliRunner

        from docuflow.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "Run a workflow from a YAML config" in result.output

    def test_run_missing_config(self):
        from click.testing import CliRunner

        from docuflow.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "nonexistent.yaml", "doc.pdf"])
        assert result.exit_code != 0
        assert "Config not found" in result.output


# ---------------------------------------------------------------------------
# Dict-based parser config
# ---------------------------------------------------------------------------


class TestParserDictConfig:
    def test_parser_dict_tesseract(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "parser": {
                "type": "tesseract",
                "languages": ["eng", "fra"],
                "dpi": 300,
                "preprocess": ["deskew", "threshold"],
            },
        })
        assert isinstance(cfg.parser, dict)
        assert cfg.parser_type == "tesseract"

        pipeline = cfg.build_pipeline()
        parser = pipeline._resolve_parser()
        from docuflow.parsing.tesseract_parser import TesseractParser
        assert isinstance(parser, TesseractParser)
        assert parser.languages == ["eng", "fra"]
        assert parser.dpi == 300
        assert parser.preprocess_steps == ["deskew", "threshold"]

    def test_parser_dict_smart(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "parser": {
                "type": "smart",
                "languages": ["eng", "deu"],
                "dpi": 250,
                "min_text_length": 50,
            },
        })
        pipeline = cfg.build_pipeline()
        parser = pipeline._resolve_parser()
        from docuflow.parsing.smart_parser import SmartParser
        assert isinstance(parser, SmartParser)
        assert parser.ocr_languages == ["eng", "deu"]
        assert parser.dpi == 250
        assert parser.min_text_length == 50

    def test_parser_dict_pdfplumber(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "parser": {"type": "pdfplumber"},
        })
        pipeline = cfg.build_pipeline()
        parser = pipeline._resolve_parser()
        from docuflow.parsing.pdfplumber_parser import PdfplumberParser
        assert isinstance(parser, PdfplumberParser)

    def test_parser_dict_defaults_to_auto(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "parser": {},
        })
        assert cfg.parser_type == "auto"

    def test_parser_string_still_works(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "parser": "tesseract",
        })
        pipeline = cfg.build_pipeline()
        parser = pipeline._resolve_parser()
        from docuflow.parsing.tesseract_parser import TesseractParser
        assert isinstance(parser, TesseractParser)
        assert parser.languages == ["eng"]


# ---------------------------------------------------------------------------
# Dict-based privacy config (all fields)
# ---------------------------------------------------------------------------


class TestPrivacyDictConfig:
    def test_privacy_all_fields(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": "presidio",
                "mode": "pseudonymize",
                "reversible": True,
                "fail_closed": False,
                "entities": ["PERSON", "EMAIL_ADDRESS"],
                "score_threshold": 0.5,
                "anonymize_before_llm": True,
                "log_scrubbing": False,
                "language": "de",
            },
        })
        policy = cfg.build_privacy()
        from docuflow.privacy.policy import PrivacyPolicy
        assert isinstance(policy, PrivacyPolicy)
        assert policy.mode.value == "pseudonymize"
        assert policy.reversible is True
        assert policy.fail_closed is False
        assert policy.entities == ["PERSON", "EMAIL_ADDRESS"]
        assert policy.score_threshold == 0.5
        assert policy.log_scrubbing is False
        assert policy.provider.language == "de"

    def test_privacy_provider_dict(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": {"language": "fr"},
                "mode": "redact",
                "reversible": False,
            },
        })
        policy = cfg.build_privacy()
        assert policy.provider.language == "fr"
        assert policy.mode.value == "redact"

    def test_privacy_with_mapping_store_path(self):
        import tempfile
        store_dir = tempfile.mkdtemp()
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": "presidio",
                "mode": "pseudonymize",
                "reversible": True,
                "mapping_store": store_dir,
            },
        })
        policy = cfg.build_privacy()
        from docuflow.privacy.mapping_store import LocalMappingStore
        assert isinstance(policy.mapping_store, LocalMappingStore)
        assert str(policy.mapping_store.base_path) == store_dir

    def test_privacy_with_mapping_store_dict(self):
        import tempfile
        store_dir = tempfile.mkdtemp()
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": "presidio",
                "mode": "pseudonymize",
                "reversible": True,
                "mapping_store": {"path": store_dir},
            },
        })
        policy = cfg.build_privacy()
        from docuflow.privacy.mapping_store import LocalMappingStore
        assert isinstance(policy.mapping_store, LocalMappingStore)

    def test_privacy_minimal_still_works(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": "presidio",
                "mode": "redact",
                "reversible": False,
            },
        })
        policy = cfg.build_privacy()
        assert policy.mode.value == "redact"
        assert policy.fail_closed is True
        assert policy.reversible is False

    def test_privacy_provider_dictionary_type(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": {
                    "type": "dictionary",
                    "mask": {"Acme Corp": "ORG"},
                    "replacements": {"PRJ-1234": "[PROJECT-CODE]"},
                },
                "mode": "redact",
                "reversible": False,
            },
        })
        policy = cfg.build_privacy()
        from docuflow.privacy.dictionary_provider import DictionaryProvider
        assert isinstance(policy.provider, DictionaryProvider)
        assert policy.provider.mask == {"Acme Corp": "ORG"}
        assert policy.provider.replacements == {"PRJ-1234": "[PROJECT-CODE]"}

    def test_privacy_provider_composite_type(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": {
                    "type": "composite",
                    "providers": [
                        {"type": "presidio", "language": "en"},
                        {"type": "dictionary", "mask": {"Acme Corp": "ORG"}},
                    ],
                },
                "mode": "redact",
                "reversible": False,
            },
        })
        policy = cfg.build_privacy()
        from docuflow.privacy.composite_provider import CompositeProvider
        from docuflow.privacy.dictionary_provider import DictionaryProvider
        from docuflow.privacy.presidio_provider import PresidioProvider
        assert isinstance(policy.provider, CompositeProvider)
        assert len(policy.provider.providers) == 2
        assert isinstance(policy.provider.providers[0], PresidioProvider)
        assert isinstance(policy.provider.providers[1], DictionaryProvider)

    def test_privacy_provider_explicit_presidio_type(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": {"type": "presidio", "language": "fr"},
                "mode": "redact",
                "reversible": False,
            },
        })
        policy = cfg.build_privacy()
        assert policy.provider.language == "fr"

    def test_privacy_provider_unknown_type_raises(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "privacy": {
                "provider": {"type": "nonexistent"},
                "mode": "redact",
                "reversible": False,
            },
        })
        with pytest.raises(ValueError, match="Unknown privacy provider type"):
            cfg.build_privacy()


# ---------------------------------------------------------------------------
# Dict-based storage config
# ---------------------------------------------------------------------------


class TestStorageDictConfig:
    def test_storage_dict_local(self):
        import tempfile
        store_dir = tempfile.mkdtemp()
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "storage": {"type": "local", "path": store_dir},
        })
        pipeline = cfg.build_pipeline()
        storage = pipeline._resolve_storage()
        from docuflow.storage.local import LocalDocumentStore
        assert isinstance(storage, LocalDocumentStore)
        assert str(storage.base_path) == store_dir

    def test_storage_string_still_works(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "storage": "local",
        })
        pipeline = cfg.build_pipeline()
        storage = pipeline._resolve_storage()
        from docuflow.storage.local import LocalDocumentStore
        assert isinstance(storage, LocalDocumentStore)

    def test_storage_none_default(self):
        cfg = load_workflow_config({"schema": {"a": {"type": "str"}}})
        assert cfg.storage is None
        pipeline = cfg.build_pipeline()
        assert pipeline._resolve_storage() is None


# ---------------------------------------------------------------------------
# Dict-based LLM config
# ---------------------------------------------------------------------------


class TestLLMDictConfig:
    def test_llm_max_retries(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "llm": {"max_retries": 5},
        })
        pipeline = cfg.build_pipeline()
        llm = pipeline._resolve_llm()
        assert llm.max_retries == 5

    def test_llm_extra_kwargs(self):
        cfg = load_workflow_config({
            "schema": {"a": {"type": "str"}},
            "llm": {"top_p": 0.9, "frequency_penalty": 0.5},
        })
        pipeline = cfg.build_pipeline()
        llm = pipeline._resolve_llm()
        assert llm.extra_kwargs.get("top_p") == 0.9
        assert llm.extra_kwargs.get("frequency_penalty") == 0.5

    def test_llm_default_no_kwargs(self):
        cfg = load_workflow_config({"schema": {"a": {"type": "str"}}})
        pipeline = cfg.build_pipeline()
        llm = pipeline._resolve_llm()
        assert llm.max_retries == 3
        assert llm.extra_kwargs == {}


# ---------------------------------------------------------------------------
# Export roundtrip with new config shapes
# ---------------------------------------------------------------------------


class TestExportExtended:
    def test_export_parser_dict_roundtrip(self):
        from docuflow.parsing.tesseract_parser import TesseractParser

        parser = TesseractParser(languages=["eng", "spa"], dpi=400)
        pipeline = DocumentPipeline(parser=parser, model="openai/gpt-4o")

        from pydantic import BaseModel
        class S(BaseModel):
            x: str

        config = export_config(pipeline, S)
        assert config["parser"]["type"] == "tesseract"
        assert config["parser"]["languages"] == ["eng", "spa"]
        assert config["parser"]["dpi"] == 400

        cfg = load_workflow_config(config)
        rebuilt = cfg.build_pipeline()
        rebuilt_parser = rebuilt._resolve_parser()
        assert isinstance(rebuilt_parser, TesseractParser)
        assert rebuilt_parser.languages == ["eng", "spa"]
        assert rebuilt_parser.dpi == 400

    def test_export_llm_kwargs_roundtrip(self):
        from pydantic import BaseModel
        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline(llm_kwargs={"max_retries": 7, "top_p": 0.8})
        config = export_config(pipeline, S)
        assert config["llm"]["max_retries"] == 7
        assert config["llm"]["top_p"] == 0.8

        cfg = load_workflow_config(config)
        rebuilt = cfg.build_pipeline()
        llm = rebuilt._resolve_llm()
        assert llm.max_retries == 7
        assert llm.extra_kwargs["top_p"] == 0.8

    def test_export_storage_roundtrip(self):
        import tempfile

        from pydantic import BaseModel
        class S(BaseModel):
            x: str

        store_dir = tempfile.mkdtemp()
        pipeline = DocumentPipeline(storage={"type": "local", "path": store_dir})
        config = export_config(pipeline, S)
        assert config["storage"]["type"] == "local"
        assert config["storage"]["path"] == store_dir

    def test_export_no_extras_stays_clean(self):
        from pydantic import BaseModel
        class S(BaseModel):
            x: str

        pipeline = DocumentPipeline()
        config = export_config(pipeline, S)
        assert "llm" not in config
        assert "storage" not in config
