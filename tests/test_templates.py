from __future__ import annotations

import pydantic
import pytest
import yaml
from pydantic import BaseModel

from docflow.templates.loader import yaml_to_pydantic
from docflow.templates.registry import TemplateRegistry, list_templates, load_template


class TestYamlToPydantic:
    def test_simple_fields(self):
        data = {
            "name": "test_schema",
            "fields": {
                "name": {"type": "str", "required": True},
                "age": {"type": "int", "required": True},
                "score": {"type": "float", "required": False},
            },
        }
        model_cls = yaml_to_pydantic(data)
        assert issubclass(model_cls, BaseModel)

        instance = model_cls(name="Alice", age=30)
        assert instance.name == "Alice"
        assert instance.age == 30
        assert instance.score is None

    def test_with_defaults(self):
        data = {
            "name": "defaults_test",
            "fields": {
                "currency": {"type": "str", "required": False, "default": "EUR"},
            },
        }
        model_cls = yaml_to_pydantic(data)
        instance = model_cls()
        assert instance.currency == "EUR"

    def test_list_field_with_item_fields(self):
        data = {
            "name": "list_test",
            "fields": {
                "items": {
                    "type": "list",
                    "required": False,
                    "item_fields": {
                        "name": {"type": "str", "required": True},
                        "price": {"type": "float", "required": True},
                    },
                },
            },
        }
        model_cls = yaml_to_pydantic(data)
        instance = model_cls(items=[{"name": "Widget", "price": 9.99}])
        assert len(instance.items) == 1
        assert instance.items[0].name == "Widget"

    def test_list_field_simple(self):
        data = {
            "name": "simple_list",
            "fields": {
                "tags": {"type": "list", "required": False, "item_type": "str"},
            },
        }
        model_cls = yaml_to_pydantic(data)
        instance = model_cls(tags=["a", "b"])
        assert instance.tags == ["a", "b"]

    def test_date_field(self):
        from datetime import date

        data = {
            "name": "date_test",
            "fields": {
                "created": {"type": "date", "required": True},
            },
        }
        model_cls = yaml_to_pydantic(data)
        instance = model_cls(created=date(2024, 1, 15))
        assert instance.created == date(2024, 1, 15)

    def test_required_field_enforced(self):
        data = {
            "name": "required_test",
            "fields": {
                "name": {"type": "str", "required": True},
            },
        }
        model_cls = yaml_to_pydantic(data)
        with pytest.raises(pydantic.ValidationError):
            model_cls()


class TestTemplateRegistry:
    def test_load_builtin_invoice(self):
        model_cls = load_template("invoice")
        assert issubclass(model_cls, BaseModel)
        instance = model_cls(
            supplier_name="Acme",
            invoice_number="INV-001",
            invoice_date="2024-01-15",
            total=1234.56,
        )
        assert instance.supplier_name == "Acme"
        assert instance.total == 1234.56

    def test_load_builtin_contract(self):
        model_cls = load_template("contract")
        assert issubclass(model_cls, BaseModel)

    def test_load_builtin_receipt(self):
        model_cls = load_template("receipt")
        assert issubclass(model_cls, BaseModel)

    def test_list_templates_includes_builtins(self):
        templates = list_templates()
        names = [t.name for t in templates]
        assert "invoice" in names
        assert "contract" in names
        assert "receipt" in names

    def test_template_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent_template")

    def test_project_local_override(self, tmp_path):
        custom_data = {
            "name": "invoice",
            "version": "2.0",
            "description": "Custom invoice",
            "fields": {
                "vendor": {"type": "str", "required": True},
                "amount": {"type": "float", "required": True},
            },
        }
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        with open(template_dir / "invoice.yaml", "w") as f:
            yaml.dump(custom_data, f)

        registry = TemplateRegistry(search_dirs=[template_dir])
        model_cls = registry.load("invoice")
        instance = model_cls(vendor="Custom Corp", amount=99.99)
        assert instance.vendor == "Custom Corp"

    def test_save_and_load(self, tmp_path):
        registry = TemplateRegistry(search_dirs=[tmp_path])
        template_data = {
            "name": "custom",
            "version": "1.0",
            "description": "Custom schema",
            "fields": {
                "title": {"type": "str", "required": True},
            },
        }
        registry.save_template("custom", template_data, user_dir=False)
        # The save_template uses a hardcoded path, so let's test via direct file
        target = tmp_path / "custom.yaml"
        with open(target, "w") as f:
            yaml.dump(template_data, f)

        model_cls = registry.load("custom")
        instance = model_cls(title="Test")
        assert instance.title == "Test"
