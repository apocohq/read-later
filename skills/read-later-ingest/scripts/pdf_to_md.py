# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf4llm>=1.28,<2",
# ]
# ///
"""
PDF bytes on stdin → one JSON object on stdout: {"markdown", "pages", "metadata"}.

Run by ingest.py as a subprocess (`uv run pdf_to_md.py`) so that PyMuPDF and its layout model, about
250 MB, are downloaded only on an agent that actually meets a PDF. Deterministic and offline: OCR off,
images dropped, running heads and page numbers removed.
"""
import json
import sys

import pymupdf
import pymupdf4llm

data = sys.stdin.buffer.read()
doc = pymupdf.open(stream=data, filetype="pdf")
md = pymupdf4llm.to_markdown(doc, use_ocr=False, header=False, footer=False, show_progress=False)
json.dump({"markdown": md, "pages": doc.page_count, "metadata": doc.metadata or {}}, sys.stdout)
