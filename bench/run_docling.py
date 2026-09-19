"""Runner Docling: PDF -> Markdown, com faixa de páginas opcional.

Uso:
    python run_docling.py <pdf> <saida.md> [ini-fim]   # ini-fim 1-indexado, inclusivo

Ex.: python run_docling.py pdfs/alares_3.pdf out/alares_3.docling.md 3-8
"""
import sys
import time

from docling.document_converter import DocumentConverter

pdf, out = sys.argv[1], sys.argv[2]
page_range = None
if len(sys.argv) > 3:
    a, b = sys.argv[3].split("-")
    page_range = (int(a), int(b))

t0 = time.time()
conv = DocumentConverter()
res = conv.convert(pdf, page_range=page_range) if page_range else conv.convert(pdf)
md = res.document.export_to_markdown()
dt = time.time() - t0

with open(out, "w", encoding="utf-8") as f:
    f.write(md)
print(f"[docling] {pdf} -> {out} em {dt:.1f}s | {len(md)} chars | pipes={md.count('|')}")
