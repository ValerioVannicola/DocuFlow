import asyncio

from docuflow.documents.models import Document, DocumentMetadata
from docuflow.parsing.docling_parser import DoclingParser


async def main():
    doc = Document(
        id="test",
        metadata=DocumentMetadata(
            file_name="test_table.pdf",
            file_path="test_table.pdf",
            mime_type="application/pdf",
        ),
    )
    parser = DoclingParser()
    result = await parser.parse(doc)
    print(f"Pages: {len(result.pages)}")
    for page in result.pages:
        print(f"  Page {page.page_number}: {page.block_count} blocks, {page.table_count} tables")
        for t in page.tables:
            print(f"    Table: {t.num_rows}x{t.num_cols}, {len(t.cells)} cells")
            for cell in t.cells:
                h = ""
                if cell.row_headers or cell.col_headers:
                    h = f" (row_h={cell.row_headers}, col_h={cell.col_headers})"
                hdr = " [HEADER]" if cell.is_column_header else ""
                rhdr = " [ROW_HDR]" if cell.is_row_header else ""
                print(f"      [{cell.row},{cell.col}] '{cell.text}'{hdr}{rhdr}{h}")
            print(f"    Records: {t.to_dict_records()}")

asyncio.run(main())
