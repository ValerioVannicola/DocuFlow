from __future__ import annotations

import json

from docflow.extraction.llm.base import LLMAdapter
from docflow.extraction.models import ExtractionResult, ReviewVerdict

REVIEWER_SYSTEM_PROMPT = """You are a document extraction reviewer. You will receive:
1. Extracted data from a document (JSON)
2. Evidence supporting each extracted field
3. The original document text
4. A specific review instruction from the user

Your job is to review the extraction according to the instruction and decide if it should \
be approved or not approved.

Return ONLY a JSON object with exactly these two fields:
{
  "verdict": "Approved" or "Not Approved",
  "reasoning": "your explanation for the decision"
}

The verdict MUST be exactly "Approved" or "Not Approved" — no other values.
Be strict: if something looks wrong or suspicious, set verdict to "Not Approved".
Return ONLY the JSON object, nothing else."""


class LLMReviewer:
    def __init__(
        self,
        name: str,
        prompt: str,
        llm: LLMAdapter,
    ):
        self.name = name
        self.prompt = prompt
        self.llm = llm

    def _build_messages(
        self, result: ExtractionResult, document_text: str,
    ) -> list[dict]:
        evidence_summary = {}
        for field_name, field in result.fields.items():
            evidence_summary[field_name] = {
                "value": field.value,
                "confidence": field.confidence,
                "evidence": [
                    {"page": e.page_number, "text": e.text}
                    for e in field.evidence
                ],
            }

        user_content = (
            f"## Review Instruction\n{self.prompt}\n\n"
            f"## Extracted Data\n```json\n"
            f"{json.dumps(result.data, indent=2, default=str)}\n```\n\n"
            f"## Field Evidence\n```json\n"
            f"{json.dumps(evidence_summary, indent=2, default=str)}\n```\n\n"
            f"## Document Text\n{document_text[:5000]}\n\n"
            "Review the extraction according to the instruction above. "
            'Return JSON with "verdict" ("Approved" or "Not Approved") '
            'and "reasoning" keys.'
        )

        return [
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def acheck(
        self, result: ExtractionResult, document_text: str = "",
    ) -> ReviewVerdict:
        messages = self._build_messages(result, document_text)

        usage: dict = {}
        try:
            response = await self.llm.complete(
                messages, temperature=0.0,
                response_format={"type": "json_object"},
            )
            usage = response.usage or {}
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
        except Exception as exc:
            return ReviewVerdict(
                reviewer=self.name,
                verdict="Not Approved",
                reasoning=f"Reviewer failed: {exc}",
                usage=usage,
            )

        raw_verdict = str(parsed.get("verdict", "Not Approved"))
        verdict = "Approved" if raw_verdict.lower().startswith("approved") else "Not Approved"
        reasoning = str(parsed.get("reasoning", ""))

        return ReviewVerdict(
            reviewer=self.name,
            verdict=verdict,
            reasoning=reasoning,
            usage=usage,
        )

    def check(self, result: ExtractionResult) -> str | None:
        return None
