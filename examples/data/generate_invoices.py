"""Generate realistic sample invoice PDFs for DocFlow notebooks."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


def _draw_invoice(
    path: Path,
    inv_number: str,
    inv_date: str,
    due_date: str,
    po_number: str,
    supplier: dict,
    bill_to: dict,
    ship_to: dict,
    line_items: list[dict],
    tax_lines: list[dict],
    notes: str,
    payment_terms: str,
    bank_details: dict,
) -> None:
    doc = fitz.open()

    # --- Page 1 ---
    page = doc.new_page(width=612, height=792)
    black = (0, 0, 0)
    gray = (0.4, 0.4, 0.4)
    dark_blue = (0.1, 0.15, 0.35)
    light_gray = (0.93, 0.93, 0.93)
    header_bg = (0.1, 0.15, 0.35)
    white = (1, 1, 1)

    # Header bar
    page.draw_rect(fitz.Rect(0, 0, 612, 70), color=None, fill=header_bg)
    page.insert_text((40, 45), supplier["name"], fontsize=20, color=white, fontname="helv")
    page.insert_text((400, 30), "INVOICE", fontsize=24, color=white, fontname="helv")
    page.insert_text((400, 50), f"#{inv_number}", fontsize=11, color=(0.7, 0.75, 0.9), fontname="helv")

    # Supplier details (left column)
    y = 95
    page.insert_text((40, y), "From:", fontsize=8, color=gray, fontname="helv")
    y += 14
    page.insert_text((40, y), supplier["name"], fontsize=9, color=black, fontname="helv")
    y += 12
    for line in supplier["address"]:
        page.insert_text((40, y), line, fontsize=8, color=gray, fontname="helv")
        y += 11
    page.insert_text((40, y), f"Tax ID: {supplier['tax_id']}", fontsize=8, color=gray, fontname="helv")
    y += 11
    page.insert_text((40, y), f"Phone: {supplier['phone']}", fontsize=8, color=gray, fontname="helv")
    y += 11
    page.insert_text((40, y), f"Email: {supplier['email']}", fontsize=8, color=gray, fontname="helv")

    # Invoice meta (right column)
    meta_x = 380
    y = 95
    meta = [
        ("Invoice Date:", inv_date),
        ("Due Date:", due_date),
        ("PO Number:", po_number),
        ("Payment Terms:", payment_terms),
    ]
    for label, val in meta:
        page.insert_text((meta_x, y), label, fontsize=8, color=gray, fontname="helv")
        page.insert_text((meta_x + 85, y), val, fontsize=8, color=black, fontname="helv")
        y += 14

    # Bill To / Ship To
    y = 185
    page.draw_rect(fitz.Rect(40, y - 5, 290, y + 8), color=None, fill=light_gray)
    page.insert_text((45, y + 5), "BILL TO", fontsize=8, color=dark_blue, fontname="helv")
    page.draw_rect(fitz.Rect(320, y - 5, 570, y + 8), color=None, fill=light_gray)
    page.insert_text((325, y + 5), "SHIP TO", fontsize=8, color=dark_blue, fontname="helv")

    y += 20
    page.insert_text((45, y), bill_to["company"], fontsize=9, color=black, fontname="helv")
    page.insert_text((325, y), ship_to["company"], fontsize=9, color=black, fontname="helv")
    y += 12
    page.insert_text((45, y), f"Attn: {bill_to['contact']}", fontsize=8, color=gray, fontname="helv")
    page.insert_text((325, y), f"Attn: {ship_to['contact']}", fontsize=8, color=gray, fontname="helv")
    y += 11
    for bl, sl in zip(bill_to["address"], ship_to["address"]):
        page.insert_text((45, y), bl, fontsize=8, color=gray, fontname="helv")
        page.insert_text((325, y), sl, fontsize=8, color=gray, fontname="helv")
        y += 11

    # Line items table header
    y = 290
    col_x = [40, 55, 280, 340, 410, 480, 540]
    headers = ["#", "Description", "Qty", "Unit Price", "Tax", "Amount"]
    page.draw_rect(fitz.Rect(35, y - 5, 577, y + 10), color=None, fill=dark_blue)
    for i, (hx, hdr) in enumerate(zip(col_x, headers)):
        page.insert_text((hx, y + 7), hdr, fontsize=8, color=white, fontname="helv")

    # Line items
    y += 18
    items_per_page = 12
    subtotal = 0.0
    item_idx = 0

    def draw_line_item(pg, yy, idx, item):
        nonlocal subtotal
        amount = item["qty"] * item["unit_price"]
        subtotal += amount
        if idx % 2 == 0:
            pg.draw_rect(fitz.Rect(35, yy - 5, 577, yy + 10), color=None, fill=light_gray)
        pg.insert_text((43, yy + 7), str(idx + 1), fontsize=8, color=gray, fontname="helv")
        desc = item["description"]
        if len(desc) > 38:
            desc = desc[:38] + "..."
        pg.insert_text((58, yy + 7), desc, fontsize=8, color=black, fontname="helv")
        pg.insert_text((283, yy + 7), f"{item['qty']:.0f}", fontsize=8, color=black, fontname="helv")
        pg.insert_text((345, yy + 7), f"${item['unit_price']:,.2f}", fontsize=8, color=black, fontname="helv")
        pg.insert_text((415, yy + 7), f"{item['tax_rate']}%", fontsize=8, color=gray, fontname="helv")
        pg.insert_text((485, yy + 7), f"${amount:,.2f}", fontsize=8, color=black, fontname="helv")
        return yy + 16

    for item in line_items[:items_per_page]:
        y = draw_line_item(page, y, item_idx, item)
        item_idx += 1

    remaining = line_items[items_per_page:]

    # --- Page 2 (if needed for remaining items + totals) ---
    if remaining:
        page = doc.new_page(width=612, height=792)
        page.insert_text((40, 40), f"Invoice #{inv_number} — continued", fontsize=10, color=gray, fontname="helv")

        y = 65
        page.draw_rect(fitz.Rect(35, y - 5, 577, y + 10), color=None, fill=dark_blue)
        for hx, hdr in zip(col_x, headers):
            page.insert_text((hx, y + 7), hdr, fontsize=8, color=white, fontname="helv")
        y += 18
        for item in remaining:
            y = draw_line_item(page, y, item_idx, item)
            item_idx += 1

    # Totals section (on current page)
    y += 15
    page.draw_line(fitz.Point(350, y), fitz.Point(577, y), color=gray, width=0.5)
    y += 15

    page.insert_text((355, y), "Subtotal:", fontsize=9, color=gray, fontname="helv")
    page.insert_text((485, y), f"${subtotal:,.2f}", fontsize=9, color=black, fontname="helv")
    y += 16

    total_tax = 0.0
    for tl in tax_lines:
        tax_amount = subtotal * tl["rate"] / 100
        total_tax += tax_amount
        page.insert_text((355, y), f"{tl['label']} ({tl['rate']}%):", fontsize=8, color=gray, fontname="helv")
        page.insert_text((485, y), f"${tax_amount:,.2f}", fontsize=8, color=black, fontname="helv")
        y += 14

    if any(tl.get("discount") for tl in tax_lines):
        pass

    y += 4
    page.draw_line(fitz.Point(350, y), fitz.Point(577, y), color=dark_blue, width=1.0)
    y += 18
    grand_total = subtotal + total_tax
    page.draw_rect(fitz.Rect(345, y - 10, 580, y + 8), color=None, fill=dark_blue)
    page.insert_text((355, y + 4), "TOTAL DUE:", fontsize=11, color=white, fontname="helv")
    page.insert_text((470, y + 4), f"${grand_total:,.2f}", fontsize=11, color=white, fontname="helv")

    # Payment info
    y += 35
    page.insert_text((40, y), "Payment Information", fontsize=10, color=dark_blue, fontname="helv")
    y += 16
    for label, val in bank_details.items():
        page.insert_text((40, y), f"{label}:", fontsize=8, color=gray, fontname="helv")
        page.insert_text((160, y), val, fontsize=8, color=black, fontname="helv")
        y += 12

    # Notes
    y += 10
    page.insert_text((40, y), "Notes & Terms", fontsize=10, color=dark_blue, fontname="helv")
    y += 16
    for note_line in notes.split("\n"):
        page.insert_text((40, y), note_line, fontsize=8, color=gray, fontname="helv")
        y += 11

    # Footer
    page.draw_line(fitz.Point(40, 755), fitz.Point(572, 755), color=light_gray, width=0.5)
    page.insert_text((40, 770), f"Thank you for your business  |  {supplier['name']}  |  {supplier['email']}",
                     fontsize=7, color=gray, fontname="helv")
    page.insert_text((520, 770), f"Page {len(doc)}/{len(doc)}", fontsize=7, color=gray, fontname="helv")

    # Page number on page 1 if multi-page
    if len(doc) > 1:
        p1 = doc[0]
        p1.draw_line(fitz.Point(40, 755), fitz.Point(572, 755), color=light_gray, width=0.5)
        p1.insert_text((520, 770), f"Page 1/{len(doc)}", fontsize=7, color=gray, fontname="helv")

    doc.save(str(path))
    doc.close()


def generate_all(output_dir: Path | None = None) -> list[Path]:
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    # --- Invoice 1: Complex multi-page, mixed tax rates ---
    _draw_invoice(
        path=output_dir / "sample_invoice.pdf",
        inv_number="INV-2024-1847",
        inv_date="November 15, 2024",
        due_date="December 15, 2024",
        po_number="PO-90281",
        supplier={
            "name": "Meridian Dynamics Ltd",
            "address": ["47 Innovation Drive, Suite 300", "Cambridge, MA 02142", "United States"],
            "tax_id": "84-2917305",
            "phone": "+1 (617) 555-0194",
            "email": "billing@meridiandynamics.com",
        },
        bill_to={
            "company": "Northwind Traders Inc.",
            "contact": "Sarah Chen, Procurement Manager",
            "address": ["1200 Market Street, Floor 8", "San Francisco, CA 94103", "United States"],
        },
        ship_to={
            "company": "Northwind Traders — Warehouse B",
            "contact": "James Rodriguez, Receiving",
            "address": ["800 Industrial Blvd, Dock 4", "Oakland, CA 94607", "United States"],
        },
        line_items=[
            {"description": "Enterprise Data Platform License (Annual)", "qty": 1, "unit_price": 24500.00, "tax_rate": 8.25},
            {"description": "Additional User Seats (50-pack)", "qty": 3, "unit_price": 2200.00, "tax_rate": 8.25},
            {"description": "Premium Support & SLA Package (12 months)", "qty": 1, "unit_price": 8750.00, "tax_rate": 8.25},
            {"description": "On-site Installation & Configuration", "qty": 40, "unit_price": 175.00, "tax_rate": 8.25},
            {"description": "Custom API Integration Development", "qty": 120, "unit_price": 195.00, "tax_rate": 8.25},
            {"description": "Data Migration Service (per TB)", "qty": 12, "unit_price": 450.00, "tax_rate": 8.25},
            {"description": "Training Workshop — Admin (full day)", "qty": 3, "unit_price": 1800.00, "tax_rate": 0},
            {"description": "Training Workshop — End Users (half day)", "qty": 5, "unit_price": 950.00, "tax_rate": 0},
            {"description": "SSL Certificate (Wildcard, 2-year)", "qty": 2, "unit_price": 320.00, "tax_rate": 8.25},
            {"description": "Dedicated Cloud Hosting — Setup Fee", "qty": 1, "unit_price": 3500.00, "tax_rate": 8.25},
            {"description": "Dedicated Cloud Hosting (monthly, prepaid x6)", "qty": 6, "unit_price": 1250.00, "tax_rate": 8.25},
            {"description": "Backup & Disaster Recovery Module", "qty": 1, "unit_price": 4200.00, "tax_rate": 8.25},
            {"description": "Security Audit & Penetration Test", "qty": 1, "unit_price": 6500.00, "tax_rate": 8.25},
            {"description": "Compliance Documentation Package (SOC 2)", "qty": 1, "unit_price": 3800.00, "tax_rate": 0},
            {"description": "Hardware Token (YubiKey 5 NFC)", "qty": 25, "unit_price": 55.00, "tax_rate": 8.25},
        ],
        tax_lines=[
            {"label": "Sales Tax (CA)", "rate": 8.25},
        ],
        notes=(
            "1. Payment due within 30 days of invoice date.\n"
            "2. Late payments subject to 1.5% monthly interest.\n"
            "3. All software licenses governed by Master Service Agreement MSA-2024-0042.\n"
            "4. Training sessions are non-refundable but may be rescheduled with 5 business days notice.\n"
            "5. Hardware items carry a 1-year manufacturer warranty."
        ),
        payment_terms="Net 30",
        bank_details={
            "Bank": "First National Bank of Cambridge",
            "Account Name": "Meridian Dynamics Ltd",
            "Routing Number": "021000089",
            "Account Number": "4819-7253-0066",
            "SWIFT/BIC": "FNBCUS33",
            "Reference": "INV-2024-1847 / PO-90281",
        },
    )
    paths.append(output_dir / "sample_invoice.pdf")

    # --- Invoice 2: Simpler, different supplier ---
    _draw_invoice(
        path=output_dir / "sample_invoice_2.pdf",
        inv_number="INV-5521",
        inv_date="November 20, 2024",
        due_date="December 20, 2024",
        po_number="PO-90281",
        supplier={
            "name": "CloudStack Solutions",
            "address": ["88 Tech Park Drive", "Austin, TX 78701", "United States"],
            "tax_id": "76-3948102",
            "phone": "+1 (512) 555-0327",
            "email": "invoices@cloudstack.io",
        },
        bill_to={
            "company": "Northwind Traders Inc.",
            "contact": "Sarah Chen, Procurement Manager",
            "address": ["1200 Market Street, Floor 8", "San Francisco, CA 94103", "United States"],
        },
        ship_to={
            "company": "Northwind Traders Inc.",
            "contact": "Sarah Chen",
            "address": ["1200 Market Street, Floor 8", "San Francisco, CA 94103", "United States"],
        },
        line_items=[
            {"description": "Cloud Infrastructure Setup (AWS)", "qty": 1, "unit_price": 5500.00, "tax_rate": 8.25},
            {"description": "Monthly Managed Services (prepaid x3)", "qty": 3, "unit_price": 3200.00, "tax_rate": 8.25},
            {"description": "CI/CD Pipeline Configuration", "qty": 1, "unit_price": 4800.00, "tax_rate": 8.25},
            {"description": "Kubernetes Cluster Deployment", "qty": 1, "unit_price": 7200.00, "tax_rate": 8.25},
            {"description": "Staff Augmentation — DevOps Engineer (40 hrs)", "qty": 40, "unit_price": 165.00, "tax_rate": 0},
            {"description": "Monitoring & Alerting Setup (Datadog)", "qty": 1, "unit_price": 2100.00, "tax_rate": 8.25},
        ],
        tax_lines=[
            {"label": "Sales Tax (CA)", "rate": 8.25},
        ],
        notes=(
            "1. Payment due within 30 days.\n"
            "2. Managed services auto-renew unless cancelled 30 days prior.\n"
            "3. Staff augmentation billed at actual hours, capped at 40/week."
        ),
        payment_terms="Net 30",
        bank_details={
            "Bank": "Silicon Valley Bank",
            "Account Name": "CloudStack Solutions LLC",
            "Routing Number": "121140399",
            "Account Number": "3310-5827-0041",
            "Reference": "INV-5521",
        },
    )
    paths.append(output_dir / "sample_invoice_2.pdf")

    # --- Invoice 3: Different amounts, same PO ---
    _draw_invoice(
        path=output_dir / "sample_invoice_3.pdf",
        inv_number="INV-2024-2003",
        inv_date="November 28, 2024",
        due_date="January 12, 2025",
        po_number="PO-90281",
        supplier={
            "name": "Meridian Dynamics Ltd",
            "address": ["47 Innovation Drive, Suite 300", "Cambridge, MA 02142", "United States"],
            "tax_id": "84-2917305",
            "phone": "+1 (617) 555-0194",
            "email": "billing@meridiandynamics.com",
        },
        bill_to={
            "company": "Northwind Traders Inc.",
            "contact": "Sarah Chen, Procurement Manager",
            "address": ["1200 Market Street, Floor 8", "San Francisco, CA 94103", "United States"],
        },
        ship_to={
            "company": "Northwind Traders — Warehouse B",
            "contact": "James Rodriguez, Receiving",
            "address": ["800 Industrial Blvd, Dock 4", "Oakland, CA 94607", "United States"],
        },
        line_items=[
            {"description": "Enterprise Data Platform License — Renewal", "qty": 1, "unit_price": 22000.00, "tax_rate": 8.25},
            {"description": "Additional User Seats (25-pack)", "qty": 2, "unit_price": 1350.00, "tax_rate": 8.25},
            {"description": "Premium Support Renewal (12 months)", "qty": 1, "unit_price": 8750.00, "tax_rate": 8.25},
            {"description": "Custom Report Builder Module", "qty": 1, "unit_price": 5400.00, "tax_rate": 8.25},
            {"description": "Advanced Analytics Add-on (per user/month x12)", "qty": 600, "unit_price": 15.00, "tax_rate": 8.25},
            {"description": "Dedicated Cloud Hosting (monthly, prepaid x12)", "qty": 12, "unit_price": 1250.00, "tax_rate": 8.25},
            {"description": "On-site Training Refresher (full day)", "qty": 2, "unit_price": 1800.00, "tax_rate": 0},
        ],
        tax_lines=[
            {"label": "Sales Tax (CA)", "rate": 8.25},
        ],
        notes=(
            "1. Payment due within 45 days of invoice date.\n"
            "2. This renewal is subject to MSA-2024-0042 (amendment 2).\n"
            "3. Analytics pricing locked for 12 months from activation date."
        ),
        payment_terms="Net 45",
        bank_details={
            "Bank": "First National Bank of Cambridge",
            "Account Name": "Meridian Dynamics Ltd",
            "Routing Number": "021000089",
            "Account Number": "4819-7253-0066",
            "SWIFT/BIC": "FNBCUS33",
            "Reference": "INV-2024-2003 / PO-90281",
        },
    )
    paths.append(output_dir / "sample_invoice_3.pdf")

    return paths


if __name__ == "__main__":
    generated = generate_all()
    for p in generated:
        print(f"Generated: {p}")
