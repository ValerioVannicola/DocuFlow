from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    amount: float = 0.0


class Invoice(BaseModel):
    supplier_name: str = Field(description="Name of the supplier or vendor")
    invoice_number: str = Field(description="Invoice reference number")
    invoice_date: str = Field(description="Date the invoice was issued")
    currency: str = Field(default="EUR", description="Currency code")
    total: float = Field(description="Total amount including tax")
    vat_amount: float | None = Field(default=None, description="VAT amount")
    line_items: list[LineItem] = Field(default_factory=list, description="Line items")
