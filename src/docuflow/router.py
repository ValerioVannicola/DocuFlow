"""Route mixed document streams to the right workflow automatically."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from docuflow._sync import run_sync
from docuflow.extraction.models import ExtractionResult, TokenUsage

DEFAULT_ROUTER_MODEL = "gemini/gemini-2.5-flash"

CLASSIFIER_SYSTEM_PROMPT = """You are a document classifier. You receive the beginning of a \
document (text or a page image) and a list of registered workflows, each handling one \
document type.

Pick the single workflow that matches the document. If none clearly matches, answer "none" \
— do NOT force a match.

Return ONLY a JSON object:
{"workflow": "<registered name or none>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}"""


class RegisteredWorkflow(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""
    pipeline: Any = None
    schema_cls: Any = None


class ClassificationDecision(BaseModel):
    workflow: str | None = None
    confidence: float = 0.0
    reason: str = ""


class RoutedResult(BaseModel):
    file_path: str
    file_name: str
    workflow: str | None = None
    classification_confidence: float = 0.0
    classification_reason: str = ""
    success: bool = False
    error: str = ""
    result: ExtractionResult | None = None


class RoutedReport(BaseModel):
    total: int = 0
    results: list[RoutedResult] = Field(default_factory=list)
    usage: TokenUsage | None = None

    @property
    def by_workflow(self) -> dict[str, list[RoutedResult]]:
        grouped: dict[str, list[RoutedResult]] = {}
        for r in self.results:
            if r.workflow is not None:
                grouped.setdefault(r.workflow, []).append(r)
        return grouped

    @property
    def unclassified(self) -> list[RoutedResult]:
        return [r for r in self.results if r.workflow is None]

    @property
    def failed(self) -> list[RoutedResult]:
        return [r for r in self.results if r.workflow is not None and not r.success]

    def to_csv(self) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "file_name", "workflow", "classification_confidence",
            "success", "extraction_confidence", "needs_review", "error",
        ])
        writer.writeheader()
        for r in self.results:
            writer.writerow({
                "file_name": r.file_name,
                "workflow": r.workflow or "unclassified",
                "classification_confidence": f"{r.classification_confidence:.2f}",
                "success": r.success,
                "extraction_confidence": (
                    f"{r.result.confidence:.2f}" if r.result else ""
                ),
                "needs_review": r.result.needs_review if r.result else "",
                "error": r.error or r.classification_reason if not r.success else "",
            })
        return output.getvalue()


def _peek_text_sync(file_path: str, max_chars: int) -> str:
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        if not pdf.pages:
            return ""
        return (pdf.pages[0].extract_text() or "")[:max_chars]


class WorkflowRouter:
    """Classify each document with one cheap LLM call, then run the matching
    registered workflow. Documents that match nothing land in
    `report.unclassified` with the classifier's reason — they are never
    force-extracted with the wrong schema.

    Args:
        model: LLM model name used by the classifier.
        llm: Optional pre-configured LLM adapter.
        confidence_threshold: Minimum classification confidence for auto-routing.
        peek_chars: Number of leading characters read from text-only inputs.
    """

    def __init__(
        self,
        model: str = DEFAULT_ROUTER_MODEL,
        llm: Any = None,
        confidence_threshold: float = 0.5,
        peek_chars: int = 2000,
    ):
        self.model = model
        self._llm = llm
        self.confidence_threshold = confidence_threshold
        self.peek_chars = peek_chars
        self._workflows: dict[str, RegisteredWorkflow] = {}
        self._classify_usages: list[dict] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        workflow: str | Path | dict | None = None,
        *,
        pipeline: Any = None,
        schema: Any = None,
        description: str = "",
    ) -> None:
        """Register a workflow under a name.

        Either pass a workflow config (YAML path or dict), or an explicit
        `pipeline` + `schema` pair.
        """
        if name in self._workflows:
            raise ValueError(f"Workflow {name!r} is already registered")

        if workflow is not None:
            from docuflow.workflow_config import load_workflow_config

            config = load_workflow_config(workflow)
            pipeline = config.build_pipeline()
            schema = config.build_schema()
            if not description:
                description = config.description
        if pipeline is None or schema is None:
            raise ValueError(
                "register() needs either a workflow config or pipeline= and schema="
            )

        if not description:
            description = f"documents with fields: {', '.join(schema.model_fields)}"

        self._workflows[name] = RegisteredWorkflow(
            name=name, description=description,
            pipeline=pipeline, schema_cls=schema,
        )

    @classmethod
    def from_config(cls, source: str | Path | dict) -> WorkflowRouter:
        """Build a router from a routes config:

        ```yaml
        model: gemini/gemini-2.5-flash   # optional
        workflows:
          - name: invoice
            description: supplier invoices with totals and line items
            workflow: workflows/invoices.yaml
          - name: claim
            workflow: workflows/claims.yaml
        ```

        Relative workflow paths resolve against the config file's directory.
        """
        base_dir = Path(".")
        if isinstance(source, dict):
            data = source
        else:
            path = Path(source)
            base_dir = path.parent
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

        router = cls(model=data.get("model", DEFAULT_ROUTER_MODEL))
        for entry in data.get("workflows", []):
            workflow_ref = entry.get("workflow")
            if isinstance(workflow_ref, str) and not Path(workflow_ref).is_absolute():
                workflow_ref = str(base_dir / workflow_ref)
            router.register(
                entry["name"],
                workflow_ref,
                description=entry.get("description", ""),
            )
        return router

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _adapter(self) -> Any:
        if self._llm is None:
            from docuflow.extraction.llm.litellm_adapter import LiteLLMAdapter

            self._llm = LiteLLMAdapter(model=self.model)
        return self._llm

    def _workflow_listing(self) -> str:
        return "\n".join(
            f"- {w.name}: {w.description}" for w in self._workflows.values()
        )

    async def _peek(self, file_path: str) -> tuple[str, str | None]:
        """(text, page1_image_b64) — image only when the text layer is empty."""
        loop = asyncio.get_event_loop()
        text = ""
        try:
            text = await loop.run_in_executor(
                None, _peek_text_sync, file_path, self.peek_chars,
            )
        except Exception:
            text = ""
        if len(text.strip()) >= 50:
            return text, None

        # No usable text layer (scan/image) — classify from the first page image
        import base64
        import io as _io

        from docuflow.rendering.renderer import render_page

        image = await render_page(file_path, 0, dpi=100)
        buf = _io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return text, base64.b64encode(buf.getvalue()).decode("ascii")

    async def classify(self, file_path: str) -> ClassificationDecision:
        if not self._workflows:
            raise ValueError("No workflows registered")

        text, image_b64 = await self._peek(file_path)

        instructions = (
            f"## Registered workflows\n{self._workflow_listing()}\n\n"
            "Classify the document below. Return JSON with workflow, "
            "confidence and reason."
        )
        if image_b64 is not None:
            content: Any = [
                {"type": "text", "text": f"{instructions}\n\n## Document (first page image)"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
            ]
        else:
            content = f"{instructions}\n\n## Document (beginning)\n{text}"

        messages = [
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            response = await self._adapter().complete(
                messages, temperature=0.0,
                response_format={"type": "json_object"},
            )
            if response.usage:
                self._classify_usages.append(response.usage)
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
        except Exception as exc:
            return ClassificationDecision(reason=f"classification failed: {exc}")

        name = str(parsed.get("workflow", "none")).strip()
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        reason = str(parsed.get("reason", ""))

        if name not in self._workflows:
            return ClassificationDecision(
                confidence=confidence,
                reason=reason or f"no registered workflow matches ({name})",
            )
        if confidence < self.confidence_threshold:
            return ClassificationDecision(
                confidence=confidence,
                reason=(
                    f"matched {name!r} but confidence {confidence:.2f} is below "
                    f"threshold {self.confidence_threshold} — {reason}"
                ),
            )
        return ClassificationDecision(
            workflow=name, confidence=confidence, reason=reason,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def route(
        self, files: list[str], concurrency: int = 5,
    ) -> RoutedReport:
        if not self._workflows:
            raise ValueError("No workflows registered")

        self._classify_usages = []
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(path: str) -> RoutedResult:
            name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            async with semaphore:
                decision = await self.classify(path)
                routed = RoutedResult(
                    file_path=path,
                    file_name=name,
                    workflow=decision.workflow,
                    classification_confidence=decision.confidence,
                    classification_reason=decision.reason,
                )
                if decision.workflow is None:
                    return routed

                registered = self._workflows[decision.workflow]
                try:
                    routed.result = await registered.pipeline.run(
                        path, registered.schema_cls,
                    )
                    routed.success = True
                except Exception as exc:
                    routed.error = str(exc)
                return routed

        results = list(await asyncio.gather(*(_process(f) for f in files)))

        usage: TokenUsage | None = TokenUsage.from_usages(self._classify_usages)
        for r in results:
            if r.result is not None and r.result.usage is not None:
                usage = (usage or TokenUsage()).combined(r.result.usage)

        return RoutedReport(total=len(files), results=results, usage=usage)

    def route_sync(self, files: list[str], concurrency: int = 5) -> RoutedReport:
        return run_sync(self.route(files, concurrency=concurrency))
