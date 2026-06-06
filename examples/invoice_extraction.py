"""Example: Extract invoice data from a PDF using docflow.

Usage:
    python examples/invoice_extraction.py path/to/invoice.pdf

Requires:
    pip install docflow[all]
    Set OPENAI_API_KEY environment variable.
"""
from __future__ import annotations

import sys

from examples.schemas.invoice import Invoice


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m examples.invoice_extraction <path-to-pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    # Option 1: One-liner with built-in template
    from docflow import extract
    from docflow.templates import load_template

    invoice_template = load_template("invoice")
    result = extract(pdf_path, schema=invoice_template)
    print("=== Template-based extraction ===")
    print(result.model_dump_json(indent=2))

    # Option 2: Using a Python schema class
    result2 = extract(pdf_path, schema=Invoice)
    print("\n=== Class-based extraction ===")
    print(f"Supplier: {result2.data.get('supplier_name')}")
    print(f"Total: {result2.data.get('total')}")
    print(f"Confidence: {result2.confidence:.2f}")
    print(f"Needs review: {result2.needs_review}")

    # Show evidence for each field
    for name, field in result2.fields.items():
        if field.evidence:
            print(f"\n  {name}: {field.value}")
            for ev in field.evidence:
                print(f"    Evidence (page {ev.page_number}): {ev.text!r}")


if __name__ == "__main__":
    main()
