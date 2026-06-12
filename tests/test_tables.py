from __future__ import annotations

import json

from docuflow.documents.models import BoundingBox
from docuflow.documents.tables import Cell, Table


class TestCell:
    def test_create(self):
        cell = Cell(row=0, col=0, text="Revenue")
        assert cell.row == 0
        assert cell.col == 0
        assert cell.text == "Revenue"
        assert cell.row_span == 1
        assert cell.col_span == 1

    def test_header_cell(self):
        cell = Cell(
            row=0, col=1, text="Q3 2024",
            is_column_header=True,
        )
        assert cell.is_column_header is True
        assert cell.is_row_header is False

    def test_with_resolved_headers(self):
        cell = Cell(
            row=2, col=1, text="4,200",
            row_headers=["Net revenue"],
            col_headers=["Q3 2024"],
        )
        assert cell.row_headers == ["Net revenue"]
        assert cell.col_headers == ["Q3 2024"]

    def test_with_bbox(self):
        cell = Cell(
            row=0, col=0, text="test",
            bbox=BoundingBox(x0=10, y0=20, x1=100, y1=40),
        )
        assert cell.bbox is not None
        assert cell.bbox.width == 90

    def test_frozen(self):
        import pydantic

        cell = Cell(row=0, col=0, text="test")
        import pytest

        with pytest.raises(pydantic.ValidationError):
            cell.text = "changed"

    def test_json_roundtrip(self):
        cell = Cell(
            row=1, col=2, text="1234.56",
            row_headers=["Total"], col_headers=["Amount"],
            is_column_header=False, is_row_header=False,
        )
        data = json.loads(cell.model_dump_json())
        restored = Cell.model_validate(data)
        assert restored.text == "1234.56"
        assert restored.row_headers == ["Total"]


class TestTable:
    def _make_table(self) -> Table:
        return Table(
            num_rows=3,
            num_cols=3,
            page_number=0,
            cells=[
                Cell(row=0, col=0, text="", is_column_header=True),
                Cell(row=0, col=1, text="Q3 2024", is_column_header=True),
                Cell(row=0, col=2, text="Q3 2023", is_column_header=True),
                Cell(row=1, col=0, text="Revenue", is_row_header=True),
                Cell(
                    row=1, col=1, text="4,200",
                    row_headers=["Revenue"], col_headers=["Q3 2024"],
                ),
                Cell(
                    row=1, col=2, text="3,800",
                    row_headers=["Revenue"], col_headers=["Q3 2023"],
                ),
                Cell(row=2, col=0, text="Cost", is_row_header=True),
                Cell(
                    row=2, col=1, text="2,100",
                    row_headers=["Cost"], col_headers=["Q3 2024"],
                ),
                Cell(
                    row=2, col=2, text="1,900",
                    row_headers=["Cost"], col_headers=["Q3 2023"],
                ),
            ],
        )

    def test_create(self):
        table = self._make_table()
        assert table.num_rows == 3
        assert table.num_cols == 3
        assert len(table.cells) == 9

    def test_header_rows(self):
        table = self._make_table()
        headers = table.header_rows
        assert len(headers) == 1
        assert headers[0][1].text == "Q3 2024"

    def test_data_rows(self):
        table = self._make_table()
        rows = table.data_rows
        assert len(rows) == 2
        assert rows[0][1].text == "4,200"
        assert rows[1][1].text == "2,100"

    def test_cell_at(self):
        table = self._make_table()
        cell = table.cell_at(1, 1)
        assert cell is not None
        assert cell.text == "4,200"

    def test_cell_at_missing(self):
        table = self._make_table()
        assert table.cell_at(99, 99) is None

    def test_column_values(self):
        table = self._make_table()
        col1 = table.column_values(1)
        assert len(col1) == 2
        assert col1[0].text == "4,200"
        assert col1[1].text == "2,100"

    def test_row_values(self):
        table = self._make_table()
        row1 = table.row_values(1)
        assert len(row1) == 3
        assert row1[0].text == "Revenue"

    def test_to_dict_records(self):
        table = self._make_table()
        records = table.to_dict_records()
        assert len(records) == 2
        assert records[0]["Q3 2024"] == "4,200"
        assert records[1]["Q3 2023"] == "1,900"

    def test_cell_knows_its_headers(self):
        table = self._make_table()
        cell = table.cell_at(1, 1)
        assert cell.row_headers == ["Revenue"]
        assert cell.col_headers == ["Q3 2024"]

    def test_json_roundtrip(self):
        table = self._make_table()
        data = json.loads(table.model_dump_json())
        restored = Table.model_validate(data)
        assert restored.num_rows == 3
        assert len(restored.cells) == 9
        assert restored.cells[4].text == "4,200"

    def test_with_spans(self):
        table = Table(
            num_rows=3,
            num_cols=2,
            cells=[
                Cell(row=0, col=0, text="Header", is_column_header=True, col_span=2),
                Cell(row=1, col=0, text="A"),
                Cell(row=1, col=1, text="B"),
                Cell(row=2, col=0, text="C"),
                Cell(row=2, col=1, text="D"),
            ],
        )
        header_cell = table.cell_at(0, 0)
        assert header_cell.col_span == 2
        assert table.cell_at(0, 1) is header_cell

    def test_empty_table(self):
        table = Table()
        assert table.num_rows == 0
        assert table.cells == []
        assert table.to_dict_records() == []


class TestPageTables:
    def test_page_has_tables(self):
        from docuflow.documents.models import Page

        page = Page(page_number=0, tables=[Table(num_rows=2, num_cols=2)])
        assert page.table_count == 1

    def test_page_tables_default_empty(self):
        from docuflow.documents.models import Page

        page = Page(page_number=0)
        assert page.table_count == 0
        assert page.tables == []
