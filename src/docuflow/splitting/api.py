"""Document splitting: assign pages to named sections using an LLM."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docuflow._sync import run_sync
from docuflow.splitting.models import (
    DocumentSection,
    SectionResult,
    SplitResult,
    _DeepSectionOutput,
    _DeepSplitResponse,
    _SimpleSplitResponse,
)

# Max characters of page text sent to the LLM per page.
_MAX_PAGE_CHARS = 3000


async def split_document_async(
    path: str,
    schema: type[BaseModel] | list[DocumentSection],
    *,
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: list[int] | None = None,
    llm: Any = None,
    llm_kwargs: Mapping[str, Any] | None = None,
) -> SplitResult:
    """Assign each page of a document to one or more named sections using an LLM.

    ``schema`` accepts either:

    * A **Pydantic model class** whose field names become section names and whose
      ``Field(description=...)`` values describe what each section contains::

          class ContractSections(BaseModel):
              body: str = Field(description="Main contract terms and conditions")
              exhibits: str = Field(description="Attached exhibits and appendices")

          result = await split_document_async("contract.pdf", ContractSections)

    * A **list of** :class:`DocumentSection` instances for a more explicit approach::

          result = await split_document_async("contract.pdf", [
              DocumentSection(name="body", description="Main contract terms"),
              DocumentSection(name="exhibits", description="Attached exhibits"),
          ])

    Args:
        path: Path to the PDF document.
        schema: Section definitions — Pydantic model class or list of DocumentSection.
        model: LiteLLM model string.
        deep: When True, the LLM also returns confidence (high/medium/low) and an
            evidence statement per section explaining why those pages were assigned.
        allow_overlap: When True, a page may appear in multiple sections.
        split_rules: Optional freeform instruction that overrides the default splitting
            logic prompt (e.g. "Sections must not overlap").
        pages: Subset of 0-based page indices to consider; None means all pages.
        llm: Optional pre-configured LLM adapter instance (overrides ``model``).
        llm_kwargs: Extra keyword arguments forwarded to litellm.

    Returns:
        :class:`SplitResult` with ``sections`` mapping section names to their
        assigned pages and (in deep mode) confidence and evidence.
    """
    return await _split_document(
        path,
        schema,
        model=model,
        deep=deep,
        allow_overlap=allow_overlap,
        split_rules=split_rules,
        pages=pages,
        llm=llm,
        llm_kwargs=llm_kwargs,
    )


def split_document(
    path: str,
    schema: type[BaseModel] | list[DocumentSection],
    *,
    model: str = "gemini/gemini-2.5-flash",
    deep: bool = False,
    allow_overlap: bool = True,
    split_rules: str = "",
    pages: list[int] | None = None,
    llm: Any = None,
    llm_kwargs: Mapping[str, Any] | None = None,
) -> SplitResult:
    """Synchronous version of :func:`split_document_async`."""
    return run_sync(
        _split_document(
            path,
            schema,
            model=model,
            deep=deep,
            allow_overlap=allow_overlap,
            split_rules=split_rules,
            pages=pages,
            llm=llm,
            llm_kwargs=llm_kwargs,
        )
    )


async def _split_document(
    path: str,
    schema: type[BaseModel] | list[DocumentSection],
    *,
    model: str,
    deep: bool,
    allow_overlap: bool,
    split_rules: str,
    pages: list[int] | None,
    llm: Any,
    llm_kwargs: Mapping[str, Any] | None,
) -> SplitResult:
    input_path = Path(path)
    result = SplitResult(input_path=str(input_path), model=model)

    try:
        sections = _parse_schema(schema)
        if not sections:
            result.errors.append("No sections defined in schema.")
            return result

        page_texts = _extract_page_texts(input_path, pages)
        if not page_texts:
            result.errors.append("Could not extract any page text from the document.")
            return result

        result.total_pages = len(page_texts)
        messages = _build_messages(page_texts, sections, split_rules, allow_overlap, deep)
        response_format = _DeepSplitResponse if deep else _SimpleSplitResponse

        raw, usage = await _call_llm(
            messages,
            response_format=response_format,
            model=model,
            llm=llm,
            llm_kwargs=llm_kwargs or {},
        )
        result.usage = usage
        result.sections = _parse_response(raw, sections, deep)

        valid_pages = {p for p, _ in page_texts}
        for name, sr in result.sections.items():
            out_of_range = [p for p in sr.pages if p not in valid_pages]
            if out_of_range:
                result.warnings.append(
                    f"Section '{name}': page(s) {out_of_range} are out of range and were removed."
                )
                sr.pages = [p for p in sr.pages if p in valid_pages]

    except Exception as exc:
        result.errors.append(str(exc))

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_schema(schema: type[BaseModel] | list[DocumentSection]) -> list[DocumentSection]:
    if isinstance(schema, list):
        return schema
    sections: list[DocumentSection] = []
    for name, info in schema.model_fields.items():
        desc = info.description or name.replace("_", " ")
        sections.append(DocumentSection(name=name, description=desc))
    return sections


def _extract_page_texts(path: Path, pages: list[int] | None) -> list[tuple[int, str]]:
    """Return [(page_idx, text)] using pdfplumber."""
    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pdfplumber is required for document splitting. "
            "Install with: pip install docuflow[pdf]"
        ) from exc

    result: list[tuple[int, str]] = []
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        page_range = pages if pages is not None else range(total)
        for i in page_range:
            if 0 <= i < total:
                text = pdf.pages[i].extract_text() or ""
                result.append((i, text))
    return result


def _build_messages(
    page_texts: list[tuple[int, str]],
    sections: list[DocumentSection],
    split_rules: str,
    allow_overlap: bool,
    deep: bool,
) -> list[dict[str, str]]:
    sections_str = "\n".join(f"- {s.name}: {s.description}" for s in sections)
    pages_str = "\n\n".join(
        f"=== Page {i} ===\n{text[:_MAX_PAGE_CHARS]}"
        for i, text in page_texts
    )
    if not allow_overlap:
        overlap_note = "Each page must be assigned to exactly one section."
    else:
        overlap_note = "A page may appear in multiple sections if it belongs to more than one."

    rules = split_rules or "Assign each page to the most appropriate section(s)."
    deep_note = (
        "\nFor each section also provide:\n"
        "- confidence: 'high', 'medium', or 'low' — your certainty that these pages belong here\n"
        "- evidence: a brief explanation of why these pages were assigned to this section"
        if deep else ""
    )
    section_names = ", ".join(f'"{s.name}"' for s in sections)

    user_msg = (
        f"Document pages:\n\n{pages_str}\n\n"
        f"Split this document into the following sections:\n{sections_str}\n\n"
        f"Rules: {rules}\n{overlap_note}\n{deep_note}\n\n"
        f'Return a JSON object with a "sections" key. Each key under "sections" must be one of: {section_names}.\n'
        f'Map each section name to an object with a "pages" array of 0-based page indices.'
    )

    return [
        {
            "role": "system",
            "content": (
                "You are a document analysis assistant. "
                "Your task is to split a document into logical sections by assigning page numbers. "
                "Return only valid JSON matching the requested schema."
            ),
        },
        {"role": "user", "content": user_msg},
    ]


async def _call_llm(
    messages: list[dict[str, str]],
    *,
    response_format: type[BaseModel],
    model: str,
    llm: Any,
    llm_kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Call the LLM and return (raw_content, usage_dict)."""
    if llm is not None:
        resp = await llm.complete(messages, response_format=response_format)
        return resp.content, resp.usage if hasattr(resp, "usage") else {}

    try:
        import litellm  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "litellm is required for document splitting. "
            "Install with: pip install docuflow[llm]"
        ) from exc

    resp = await litellm.acompletion(
        model=model,
        messages=messages,
        response_format=response_format,
        temperature=0.0,
        **llm_kwargs,
    )
    content = resp.choices[0].message.content or ""
    usage: dict[str, Any] = {}
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
        try:
            cost = litellm.completion_cost(completion_response=resp)
            if cost:
                usage["cost_usd"] = round(cost, 6)
        except Exception:  # noqa: S110 — unknown model pricing; tokens still reported
            pass
    return content, usage


def _parse_response(
    raw: str,
    sections: list[DocumentSection],
    deep: bool,
) -> dict[str, SectionResult]:
    """Parse the LLM's JSON response into SectionResult objects."""
    valid_names = {s.name for s in sections}
    try:
        data = json.loads(raw)
        raw_sections = data.get("sections", {})
    except (json.JSONDecodeError, AttributeError):
        return {s.name: SectionResult() for s in sections}

    result: dict[str, SectionResult] = {}
    for name in valid_names:
        entry = raw_sections.get(name, {})
        if isinstance(entry, list):
            # LLM returned pages array directly instead of an object
            result[name] = SectionResult(pages=entry)
        elif isinstance(entry, dict):
            if deep:
                parsed = _DeepSectionOutput.model_validate(entry)
                result[name] = SectionResult(
                    pages=parsed.pages,
                    confidence=parsed.confidence,
                    evidence=parsed.evidence,
                )
            else:
                result[name] = SectionResult(pages=entry.get("pages", []))
        else:
            result[name] = SectionResult()
    return result
