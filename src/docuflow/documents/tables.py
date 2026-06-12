from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from docuflow.documents.models import BoundingBox


class Cell(BaseModel):
    model_config = ConfigDict(frozen=True)

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str = ""
    is_column_header: bool = False
    is_row_header: bool = False
    is_row_section: bool = False
    row_headers: list[str] = Field(default_factory=list)
    col_headers: list[str] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    confidence: float | None = None


class Table(BaseModel):
    table_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    num_rows: int = 0
    num_cols: int = 0
    cells: list[Cell] = Field(default_factory=list)
    page_number: int = 0
    bbox: BoundingBox | None = None
    markdown: str = ""

    @property
    def header_rows(self) -> list[list[Cell]]:
        headers: dict[int, list[Cell]] = {}
        for cell in self.cells:
            if cell.is_column_header:
                headers.setdefault(cell.row, []).append(cell)
        return [sorted(cells, key=lambda c: c.col) for _, cells in sorted(headers.items())]

    @property
    def data_rows(self) -> list[list[Cell]]:
        rows: dict[int, list[Cell]] = {}
        for cell in self.cells:
            if not cell.is_column_header and not cell.is_row_section:
                rows.setdefault(cell.row, []).append(cell)
        return [sorted(cells, key=lambda c: c.col) for _, cells in sorted(rows.items())]

    def cell_at(self, row: int, col: int) -> Cell | None:
        for cell in self.cells:
            if (
                cell.row <= row < cell.row + cell.row_span
                and cell.col <= col < cell.col + cell.col_span
            ):
                return cell
        return None

    def column_values(self, col: int) -> list[Cell]:
        return sorted(
            [c for c in self.cells if c.col == col and not c.is_column_header],
            key=lambda c: c.row,
        )

    def row_values(self, row: int) -> list[Cell]:
        return sorted(
            [c for c in self.cells if c.row == row],
            key=lambda c: c.col,
        )

    def to_dict_records(self) -> list[dict[str, str]]:
        if not self.cells:
            return []
        col_header_map: dict[int, str] = {}
        for cell in self.cells:
            if cell.is_column_header and cell.col not in col_header_map:
                col_header_map[cell.col] = cell.text

        records: list[dict[str, str]] = []
        for row_cells in self.data_rows:
            record: dict[str, str] = {}
            for cell in row_cells:
                header = cell.col_headers[0] if cell.col_headers else col_header_map.get(cell.col, f"col_{cell.col}")
                record[header] = cell.text
            if record:
                records.append(record)
        return records
