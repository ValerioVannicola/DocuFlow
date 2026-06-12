"""Generate realistic sample invoice PDFs for DocuFlow notebooks (reportlab)."""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas

PAGE_W, PAGE_H = 612, 792

BLACK = (0, 0, 0)
GRAY = (0.4, 0.4, 0.4)
DARK_BLUE = (0.1, 0.15, 0.35)
LIGHT_GRAY = (0.93, 0.93, 0.93)
HEADER_BG = (0.1, 0.15, 0.35)
WHITE = (1, 1, 1)
HEADER_ACCENT = (0.7, 0.75, 0.9)


class _PageDraw:
    """Top-left-origin drawing helper over a reportlab canvas, so layout
    coordinates read like the page is drawn from the top down."""

    def __init__(self, c: rl_canvas.Canvas, height: float = PAGE_H):
        self.c = c
        self.h = height

    def text(self, x: float, y: float, s: str, size: float = 8, color=BLACK) -> None:
        self.c.setFont("Helvetica", size)
        self.c.setFillColorRGB(*color)
        self.c.drawString(x, self.h - y, s)

    def rect(self, x0: float, y0: float, x1: float, y1: float, fill) -> None:
        self.c.setFillColorRGB(*fill)
        self.c.rect(x0, self.h - y1, x1 - x0, y1 - y0, stroke=0, fill=1)

    def line(self, x0: float, y0: float, x1: float, y1: float, color, width: float) -> None:
        self.c.setStrokeColorRGB(*color)
        self.c.setLineWidth(width)
        self.c.line(x0, self.h - y0, x1, self.h - y1)


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
    c = rl_canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    page = _PageDraw(c)

    items_per_page = 12
    remaining = line_items[items_per_page:]
    total_pages = 2 if remaining else 1

    # --- Page 1 ---

    # Header bar
    page.rect(0, 0, 612, 70, HEADER_BG)
    page.text(40, 45, supplier["name"], 20, WHITE)
    page.text(400, 30, "INVOICE", 24, WHITE)
    page.text(400, 50, f"#{inv_number}", 11, HEADER_ACCENT)

    # Supplier details (left column)
    y = 95
    page.text(40, y, "From:", 8, GRAY)
    y += 14
    page.text(40, y, supplier["name"], 9, BLACK)
    y += 12
    for line in supplier["address"]:
        page.text(40, y, line, 8, GRAY)
        y += 11
    page.text(40, y, f"Tax ID: {supplier['tax_id']}", 8, GRAY)
    y += 11
    page.text(40, y, f"Phone: {supplier['phone']}", 8, GRAY)
    y += 11
    page.text(40, y, f"Email: {supplier['email']}", 8, GRAY)

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
        page.text(meta_x, y, label, 8, GRAY)
        page.text(meta_x + 85, y, val, 8, BLACK)
        y += 14

    # Bill To / Ship To
    y = 185
    page.rect(40, y - 5, 290, y + 8, LIGHT_GRAY)
    page.text(45, y + 5, "BILL TO", 8, DARK_BLUE)
    page.rect(320, y - 5, 570, y + 8, LIGHT_GRAY)
    page.text(325, y + 5, "SHIP TO", 8, DARK_BLUE)

    y += 20
    page.text(45, y, bill_to["company"], 9, BLACK)
    page.text(325, y, ship_to["company"], 9, BLACK)
    y += 12
    page.text(45, y, f"Attn: {bill_to['contact']}", 8, GRAY)
    page.text(325, y, f"Attn: {ship_to['contact']}", 8, GRAY)
    y += 11
    for bl, sl in zip(bill_to["address"], ship_to["address"], strict=False):
        page.text(45, y, bl, 8, GRAY)
        page.text(325, y, sl, 8, GRAY)
        y += 11

    # Line items table header
    col_x = [40, 55, 280, 340, 410, 480, 540]
    headers = ["#", "Description", "Qty", "Unit Price", "Tax", "Amount"]

    def draw_table_header(pg: _PageDraw, yy: float) -> None:
        pg.rect(35, yy - 5, 577, yy + 10, DARK_BLUE)
        for hx, hdr in zip(col_x, headers, strict=False):
            pg.text(hx, yy + 7, hdr, 8, WHITE)

    y = 290
    draw_table_header(page, y)

    y += 18
    subtotal = 0.0
    item_idx = 0

    def draw_line_item(pg: _PageDraw, yy: float, idx: int, item: dict) -> float:
        nonlocal subtotal
        amount = item["qty"] * item["unit_price"]
        subtotal += amount
        if idx % 2 == 0:
            pg.rect(35, yy - 5, 577, yy + 10, LIGHT_GRAY)
        pg.text(43, yy + 7, str(idx + 1), 8, GRAY)
        desc = item["description"]
        if len(desc) > 38:
            desc = desc[:38] + "..."
        pg.text(58, yy + 7, desc, 8, BLACK)
        pg.text(283, yy + 7, f"{item['qty']:.0f}", 8, BLACK)
        pg.text(345, yy + 7, f"${item['unit_price']:,.2f}", 8, BLACK)
        pg.text(415, yy + 7, f"{item['tax_rate']}%", 8, GRAY)
        pg.text(485, yy + 7, f"${amount:,.2f}", 8, BLACK)
        return yy + 16

    for item in line_items[:items_per_page]:
        y = draw_line_item(page, y, item_idx, item)
        item_idx += 1

    # --- Page 2 (if needed for remaining items + totals) ---
    if remaining:
        # finish page 1 with its footer before moving on
        page.line(40, 755, 572, 755, LIGHT_GRAY, 0.5)
        page.text(520, 770, f"Page 1/{total_pages}", 7, GRAY)
        c.showPage()
        page = _PageDraw(c)
        page.text(40, 40, f"Invoice #{inv_number} — continued", 10, GRAY)

        y = 65
        draw_table_header(page, y)
        y += 18
        for item in remaining:
            y = draw_line_item(page, y, item_idx, item)
            item_idx += 1

    # Totals section (on current page)
    y += 15
    page.line(350, y, 577, y, GRAY, 0.5)
    y += 15

    page.text(355, y, "Subtotal:", 9, GRAY)
    page.text(485, y, f"${subtotal:,.2f}", 9, BLACK)
    y += 16

    total_tax = 0.0
    for tl in tax_lines:
        tax_amount = subtotal * tl["rate"] / 100
        total_tax += tax_amount
        page.text(355, y, f"{tl['label']} ({tl['rate']}%):", 8, GRAY)
        page.text(485, y, f"${tax_amount:,.2f}", 8, BLACK)
        y += 14

    y += 4
    page.line(350, y, 577, y, DARK_BLUE, 1.0)
    y += 18
    grand_total = subtotal + total_tax
    page.rect(345, y - 10, 580, y + 8, DARK_BLUE)
    page.text(355, y + 4, "TOTAL DUE:", 11, WHITE)
    page.text(470, y + 4, f"${grand_total:,.2f}", 11, WHITE)

    # Payment info
    y += 35
    page.text(40, y, "Payment Information", 10, DARK_BLUE)
    y += 16
    for label, val in bank_details.items():
        page.text(40, y, f"{label}:", 8, GRAY)
        page.text(160, y, val, 8, BLACK)
        y += 12

    # Notes
    y += 10
    page.text(40, y, "Notes & Terms", 10, DARK_BLUE)
    y += 16
    for note_line in notes.split("\n"):
        page.text(40, y, note_line, 8, GRAY)
        y += 11

    # Footer (last page)
    page.line(40, 755, 572, 755, LIGHT_GRAY, 0.5)
    page.text(
        40, 770,
        f"Thank you for your business  |  {supplier['name']}  |  {supplier['email']}",
        7, GRAY,
    )
    page.text(520, 770, f"Page {total_pages}/{total_pages}", 7, GRAY)

    c.save()


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
