from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel

from docuflow.templates.loader import yaml_to_pydantic

_BUILTIN_DIR = Path(__file__).parent / "builtin"
_USER_HOME_DIR = Path.home() / ".docuflow" / "templates"
_PROJECT_LOCAL_DIR = Path("docuflow_templates")


@dataclass
class TemplateInfo:
    name: str
    version: str
    description: str
    source: str  # "builtin", "user", or "project"
    path: Path


class TemplateRegistry:
    def __init__(
        self,
        search_dirs: list[Path] | None = None,
    ):
        if search_dirs is not None:
            self._dirs = search_dirs
        else:
            self._dirs = [_PROJECT_LOCAL_DIR, _USER_HOME_DIR, _BUILTIN_DIR]

    def _find_template_file(self, name: str) -> Path | None:
        for dir_path in self._dirs:
            if not dir_path.is_dir():
                continue
            for ext in (".yaml", ".yml"):
                candidate = dir_path / f"{name}{ext}"
                if candidate.is_file():
                    return candidate
        return None

    def _source_label(self, path: Path) -> str:
        resolved = path.resolve()
        if _BUILTIN_DIR.resolve() in resolved.parents or resolved.parent == _BUILTIN_DIR.resolve():
            return "builtin"
        if (
            _USER_HOME_DIR.resolve() in resolved.parents
            or resolved.parent == _USER_HOME_DIR.resolve()
        ):
            return "user"
        return "project"

    def load_raw(self, name: str) -> dict:
        path = self._find_template_file(name)
        if path is None:
            raise FileNotFoundError(f"Template not found: {name!r}")
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid template format in {path}")
        return data

    def load(self, name: str) -> type[BaseModel]:
        data = self.load_raw(name)
        return yaml_to_pydantic(data)

    def list_templates(self) -> list[TemplateInfo]:
        seen: set[str] = set()
        templates: list[TemplateInfo] = []
        for dir_path in self._dirs:
            if not dir_path.is_dir():
                continue
            for file_path in sorted(dir_path.glob("*.yaml")) + sorted(
                dir_path.glob("*.yml")
            ):
                stem = file_path.stem
                if stem in seen:
                    continue
                seen.add(stem)
                try:
                    with open(file_path) as f:
                        data = yaml.safe_load(f)
                    templates.append(
                        TemplateInfo(
                            name=data.get("name", stem),
                            version=data.get("version", "0.0"),
                            description=data.get("description", ""),
                            source=self._source_label(file_path),
                            path=file_path,
                        )
                    )
                except (OSError, yaml.YAMLError, KeyError):
                    continue
        return templates

    def save_template(self, name: str, template_data: dict, user_dir: bool = True) -> Path:
        target_dir = _USER_HOME_DIR if user_dir else _PROJECT_LOCAL_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{name}.yaml"
        with open(target_path, "w") as f:
            yaml.dump(template_data, f, default_flow_style=False, sort_keys=False)
        return target_path


_default_registry = TemplateRegistry()


def load_template(name: str) -> type[BaseModel]:
    return _default_registry.load(name)


def list_templates() -> list[TemplateInfo]:
    return _default_registry.list_templates()
