"""Render Markdown documents to PDF.

Documents are authored/stored as Markdown (the editable source of truth); for
reading we also keep a rendered PDF next to each version. This module is the one
place that turns Markdown bytes into PDF bytes, used by both the REST upload
routes and the assistant's ``upload_document`` tool.

WeasyPrint (and its ``markdown`` companion) are imported lazily inside
:func:`render_pdf` — like the Anthropic client elsewhere — so the module stays
importable (and the app/tests keep running) even where the native WeasyPrint
libraries aren't installed. In that case :func:`pdf_for` degrades to ``None`` and
the document is stored with its Markdown only.
"""
from __future__ import annotations

import logging

log = logging.getLogger("releaseit.doc_render")

MARKDOWN_CONTENT_TYPE = "text/markdown"
PDF_CONTENT_TYPE = "application/pdf"

# Extensions we treat as Markdown even when the browser sends a generic
# content-type (e.g. application/octet-stream) for an uploaded .md file.
_MARKDOWN_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")

# A deliberately plain print stylesheet — readable body text, sensible margins,
# and code/tables that don't overflow the page.
_PDF_CSS = """
@page { size: A4; margin: 2cm; }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 11pt; line-height: 1.45;
       color: #1a1a1a; }
h1, h2, h3, h4 { font-weight: 600; line-height: 1.25; margin: 1em 0 0.4em; }
h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
code, pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 9.5pt; }
pre { background: #f4f4f5; padding: 0.6em 0.8em; border-radius: 4px;
      white-space: pre-wrap; word-wrap: break-word; }
code { background: #f4f4f5; padding: 0.1em 0.3em; border-radius: 3px; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 0.6em 0; }
th, td { border: 1px solid #ccc; padding: 0.35em 0.6em; text-align: left; }
th { background: #f4f4f5; }
blockquote { margin: 0.6em 0; padding-left: 0.9em; border-left: 3px solid #ddd;
             color: #555; }
a { color: #1c4ed8; text-decoration: none; }
"""


def is_markdown(content_type: str | None, filename: str | None = None) -> bool:
    """Whether content of this type/name should be treated as Markdown."""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in (MARKDOWN_CONTENT_TYPE, "text/x-markdown"):
        return True
    name = (filename or "").lower()
    return name.endswith(_MARKDOWN_EXTENSIONS)


def render_pdf(markdown_text: str, title: str = "") -> bytes:
    """Render Markdown source to PDF bytes. Raises if WeasyPrint (or its native
    libraries) is unavailable — callers that must not fail use :func:`pdf_for`."""
    import markdown as md  # lazy: keeps the module importable without the deps
    from weasyprint import HTML

    body_html = md.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )
    safe_title = (title or "Document").replace("<", "&lt;").replace(">", "&gt;")
    html_doc = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{safe_title}</title><style>{_PDF_CSS}</style></head>"
        f"<body>{body_html}</body></html>"
    )
    return HTML(string=html_doc).write_pdf()


def pdf_for(
    content_type: str | None, content: bytes, *, filename: str | None = None, title: str = ""
) -> bytes | None:
    """Render a PDF companion for a stored version, or ``None`` when there is
    nothing to render (non-Markdown source) or the renderer is unavailable.

    Never raises: a rendering failure is logged and treated as "no PDF" so the
    upload of the Markdown itself always succeeds."""
    if not is_markdown(content_type, filename):
        return None
    try:
        return render_pdf(content.decode("utf-8", errors="replace"), title=title)
    except Exception:  # missing native libs, malformed markup, etc.
        log.exception("PDF rendering failed for document %r; storing Markdown only", title)
        return None
