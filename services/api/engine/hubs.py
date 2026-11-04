"""Tool hubs: curated sections of the site (today: PDF tools) built on registry operations.

A hub tool points at an operation (and optionally its source formats and target). /api/capabilities includes a
tool only when that operation has an advertised pair matching it, so the hub never offers anything untested,
disabled by a feature flag, or missing its engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HubTool:
    slug: str
    title: str
    description: str
    icon: str  # a Lucide icon name; the web app maps it to a component
    op: str
    group: str
    target: str | None = None  # None: any target the operation offers (transforms keep the format)
    sources: tuple[str, ...] | None = None  # None: any source format the operation accepts
    options: dict = field(default_factory=dict)  # preset settings for this tool page
    special: str | None = None  # a page with its own UI before the workspace (e.g. "scan")


@dataclass(frozen=True)
class Hub:
    id: str
    title: str
    description: str
    groups: tuple[tuple[str, str], ...]
    tools: tuple[HubTool, ...]
    not_offered: tuple[tuple[str, str], ...] = ()


OFFICE = ("docx", "doc", "odt", "rtf")

PDF_HUB = Hub(
    id="pdf",
    title="PDF tools",
    description="Organize, convert, edit, sign and secure PDFs. Every tool runs in an isolated process and your files "
                "are deleted automatically.",
    groups=(("organize", "Organize"), ("optimize", "Optimize"), ("to_pdf", "Convert to PDF"),
            ("from_pdf", "Convert from PDF"), ("edit", "Edit"), ("forms", "Forms"), ("security", "Security"),
            ("review", "Review")),
    tools=(
        # organize
        HubTool("merge-pdf", "Merge PDF", "Combine several PDFs into one, in the order you choose.", "combine", "pdf.merge", "organize"),
        HubTool("split-pdf", "Split PDF", "Split into single pages, page ranges or equal parts.", "split", "pdf.split", "organize"),
        HubTool("organize-pdf", "Organize pages", "Reorder, rotate, delete, duplicate and add blank pages on one screen.",
                "layout-grid", "pdf.organize", "organize"),
        HubTool("rotate-pdf", "Rotate PDF", "Turn all pages, or just the ones you pick, by 90, 180 or 270 degrees.",
                "rotate-cw", "pdf.rotate", "organize"),
        HubTool("extract-pdf-pages", "Extract pages", "Make a new PDF from only the pages you need.", "file-output",
                "pdf.extract_pages", "organize"),
        HubTool("delete-pdf-pages", "Delete pages", "Remove the pages you don't want.", "file-minus", "pdf.delete_pages", "organize"),
        HubTool("crop-pdf", "Crop PDF", "Trim margins, or keep just the area you draw.", "crop", "pdf.crop", "organize"),
        HubTool("resize-pdf", "Resize pages", "Fit every page onto A4, Letter or another paper size.", "scaling",
                "pdf.resize", "organize"),
        HubTool("pdf-pages-per-sheet", "Pages per sheet", "Put 2, 4, 6, 9 or 16 pages on each sheet for printing.",
                "grid-2x2", "pdf.nup", "organize"),
        # optimize
        HubTool("compress-pdf", "Compress PDF", "Make a PDF smaller by optimizing its images and structure.", "minimize-2",
                "pdf.compress", "optimize"),
        HubTool("repair-pdf", "Repair PDF", "Rebuild a damaged PDF and recover its pages.", "wrench", "pdf.repair", "optimize"),
        HubTool("ocr-pdf", "OCR PDF", "Make scanned PDFs searchable and selectable.", "scan-text", "pdf.ocr", "optimize"),
        HubTool("pdf-to-pdfa", "PDF to PDF/A", "Make an archival PDF/A copy for long-term storage.", "archive", "pdf.to_pdfa",
                "optimize"),
        # convert to PDF
        HubTool("word-to-pdf", "Word to PDF", "Turn DOCX, DOC, ODT and RTF documents into PDF.", "file-text", "doc.office",
                "to_pdf", target="pdf", sources=OFFICE),
        HubTool("powerpoint-to-pdf", "PowerPoint to PDF", "Turn PPTX, PPT and ODP slides into PDF.", "presentation",
                "pres.office", "to_pdf", target="pdf"),
        HubTool("excel-to-pdf", "Excel to PDF", "Turn XLSX, XLS, ODS and CSV spreadsheets into PDF.", "sheet",
                "sheet.to_pdf", "to_pdf", target="pdf"),
        HubTool("jpg-to-pdf", "Images to PDF", "Turn JPG, PNG, HEIC and other images into a PDF, one per page.", "image",
                "pdf.from_images", "to_pdf", target="pdf"),
        HubTool("scan-to-pdf", "Scan to PDF", "Photograph paper documents with your camera and get a clean PDF.", "camera",
                "pdf.from_images", "to_pdf", target="pdf", options={"enhance": "document", "page_size": "A4"},
                special="scan"),
        HubTool("html-to-pdf", "HTML to PDF", "Turn an HTML or Markdown file into a PDF.", "code", "doc.html_to_pdf",
                "to_pdf", target="pdf"),
        # convert from PDF
        HubTool("pdf-to-word", "PDF to Word", "Turn a PDF into an editable Word document.", "file-text", "pdf.to_docx",
                "from_pdf", target="docx"),
        HubTool("pdf-to-powerpoint", "PDF to PowerPoint", "Put each PDF page on a PowerPoint slide.", "presentation",
                "pres.from_pdf", "from_pdf", target="pptx"),
        HubTool("pdf-to-excel", "PDF to Excel", "Pull tables out of a PDF into a spreadsheet.", "sheet", "pdf.to_tables",
                "from_pdf", target="xlsx"),
        HubTool("pdf-to-jpg", "PDF to JPG", "Save each page as a JPG or PNG image.", "image", "pdf.to_images", "from_pdf",
                target="jpg"),
        HubTool("extract-pdf-images", "Extract images", "Save the photos inside a PDF at their original quality.", "images",
                "pdf.extract_images", "from_pdf"),
        HubTool("pdf-to-markdown", "PDF to Markdown", "Turn a PDF's text into Markdown, with headings and tables.", "hash",
                "pdf.to_text", "from_pdf", target="md"),
        HubTool("pdf-to-text", "PDF to text", "Get the plain text out of a PDF.", "type", "pdf.to_text", "from_pdf", target="txt"),
        # edit
        HubTool("edit-pdf", "Edit PDF", "Add text, images, shapes, highlights and drawings to pages.", "pencil-line",
                "pdf.edit", "edit"),
        HubTool("add-page-numbers", "Page numbers", "Number pages, or add a header or footer.", "list-ordered",
                "pdf.page_numbers", "edit"),
        HubTool("watermark-pdf", "Watermark", "Stamp text such as DRAFT or CONFIDENTIAL across pages.", "stamp",
                "pdf.watermark", "edit"),
        HubTool("watermark-pdf-image", "Add a logo", "Stamp an image or logo on pages. Add a PDF and an image together.",
                "image-plus", "pdf.watermark_image", "edit"),
        HubTool("edit-pdf-metadata", "Edit properties", "Change the title and author, or remove all properties.",
                "info", "pdf.metadata", "edit"),
        # forms
        HubTool("fill-pdf-form", "Fill a form", "Fill in a PDF form's fields, then flatten it if you like.", "text-cursor-input",
                "pdf.fill_form", "forms"),
        HubTool("create-pdf-form", "Create a form", "Draw text boxes, checkboxes and dropdowns to make any PDF fillable.",
                "form-input", "pdf.add_fields", "forms"),
        HubTool("pdf-form-data", "Export form data", "Get a form's fields and answers as JSON.", "braces", "pdf.form_data",
                "forms"),
        # security
        HubTool("sign-pdf", "Sign PDF", "Draw, type or upload your signature and place it on the page.", "signature",
                "pdf.sign", "security"),
        HubTool("redact-pdf", "Redact PDF", "Permanently black out names, numbers and areas.", "eraser", "pdf.redact",
                "security"),
        HubTool("protect-pdf", "Protect PDF", "Add a password with AES-256 encryption.", "lock", "pdf.protect", "security"),
        HubTool("unlock-pdf", "Unlock PDF", "Remove a password you know.", "lock-open", "pdf.unlock", "security"),
        HubTool("flatten-pdf", "Flatten PDF", "Lock filled forms and comments into the page.", "layers", "pdf.flatten",
                "security"),
        # review
        HubTool("compare-pdf", "Compare PDFs", "See what changed between two versions of a document.", "git-compare",
                "pdf.compare", "review"),
    ),
    not_offered=(
        ("AI summaries and translation", "Not offered: they would send your document's text to an AI service."),
        ("Requesting signatures from other people", "Needs accounts and email, which this site doesn't have. Sign PDF "
                                                    "adds your own visual signature."),
        ("HTML to PDF from a web address", "Fetching URLs from the server is a security risk, so upload the HTML file "
                                           "instead."),
    ),
)

HUBS = (PDF_HUB,)
