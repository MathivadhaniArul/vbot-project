from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Optional / external dependencies
# ---------------------------------------------------------------------------

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.chunking import HybridChunker

from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.tokenizer.huggingface import (
    HuggingFaceTokenizer,
)
from docling_core.transforms.serializer.markdown import (
    MarkdownParams,
    MarkdownTableSerializer,
)

from transformers import AutoTokenizer

try:
    from docling_client import DoclingClient
except ImportError:
    DoclingClient = None


from admin.chunking import build_hierarchical_chunks


# ============================================================================
# LOGGER / ROUTER
# ============================================================================

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/scrape",
    tags=["admin-scrape"],
)


# ============================================================================
# CONFIGURATION
# ============================================================================

MAX_SCRAPE_CHARS = int(
    os.getenv("MAX_SCRAPE_CHARS", "60000")
)

# URL scraping
URL_CONNECT_TIMEOUT = int(
    os.getenv("URL_CONNECT_TIMEOUT", "20")
)

URL_READ_TIMEOUT = int(
    os.getenv("URL_READ_TIMEOUT", "120")
)

URL_MAX_RETRIES = int(
    os.getenv("URL_MAX_RETRIES", "3")
)

# PDF / Docling
DOCLING_BASE_URL = os.getenv(
    "DOCLING_BASE_URL",
    "http://localhost:8004",
)

DOCLING_TIMEOUT_SECONDS = int(
    os.getenv("DOCLING_TIMEOUT_SECONDS", "550")
)

PDF_MAX_TOKENS = int(
    os.getenv("PDF_MAX_TOKENS", "256")
)

PDF_MIN_CHUNK_TOKENS = int(
    os.getenv("PDF_MIN_CHUNK_TOKENS", "40")
)

PDF_EMBED_MODEL = os.getenv(
    "PDF_EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)

MAX_CONCURRENT_PDF_CONVERSIONS = int(
    os.getenv("MAX_CONCURRENT_PDF_CONVERSIONS", "2")
)


# ============================================================================
# PDF PIPELINE
# ============================================================================

_pdf_pipeline_options = PdfPipelineOptions()

# Keep OCR disabled unless you explicitly want OCR.
_pdf_pipeline_options.do_ocr = False
_pdf_pipeline_options.images_scale = 1.0


_docling_converter = DocumentConverter(
    allowed_formats=[InputFormat.PDF],
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=_pdf_pipeline_options
        )
    },
)


_pdf_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_PDF_CONVERSIONS
)

_pdf_chunker = None
_pdf_tokenizer = None

_pdf_chunker_lock = asyncio.Lock()


# ============================================================================
# PDF TABLE SERIALIZER
# ============================================================================

class MDTableSerializerProvider(ChunkingSerializerProvider):
    """
    Makes Docling tables serialize as Markdown instead of losing
    table structure during chunking.
    """

    def get_serializer(self, doc):
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=MarkdownTableSerializer(),
            params=MarkdownParams(
                compact_tables=True
            ),
        )


# ============================================================================
# TEXT CLEANING
# ============================================================================

def _clean_pdf_text(text: str) -> str:
    """
    Normalize whitespace without destroying Markdown/table structure.
    """

    text = (text or "").replace("\u00a0", " ")

    # Normalize spaces/tabs but preserve newlines.
    text = re.sub(r"[ \t]+", " ", text)

    # Avoid huge blank-line runs.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _clean_pdf_heading(text: str) -> str:
    text = re.sub(
        r"\s+",
        " ",
        text or "",
    )

    return text.strip().rstrip(":")


def _chunk_token_count(text: str) -> int:
    if _pdf_tokenizer is None:
        return 0

    try:
        return len(
            _pdf_tokenizer.encode(
                text,
                add_special_tokens=False,
            )
        )
    except Exception:
        return 0


# ============================================================================
# PDF CHUNKER INITIALIZATION
# ============================================================================

def _ensure_pdf_chunker():
    """
    Lazily initialize the HuggingFace tokenizer + Docling HybridChunker.

    This is intentionally lazy because loading the tokenizer during module
    import makes FastAPI startup unnecessarily slow.
    """

    global _pdf_chunker
    global _pdf_tokenizer

    if _pdf_chunker is not None:
        return _pdf_chunker

    _pdf_tokenizer = AutoTokenizer.from_pretrained(
        PDF_EMBED_MODEL
    )

    tokenizer = HuggingFaceTokenizer(
        tokenizer=_pdf_tokenizer,
        max_tokens=PDF_MAX_TOKENS,
    )

    _pdf_chunker = HybridChunker(
        tokenizer=tokenizer,
        merge_peers=True,
        serializer_provider=MDTableSerializerProvider(),
        repeat_table_header=True,
    )

    return _pdf_chunker


# ============================================================================
# HEADING NORMALIZATION
# ============================================================================

def _normalize_section_path(value: Any) -> list[str]:
    """
    Accept:

        ["Admissions", "Eligibility"]

    or:

        "Admissions > Eligibility"

    and normalize both to:

        ["Admissions", "Eligibility"]
    """

    if isinstance(value, (list, tuple)):
        result = []

        for item in value:
            cleaned = _clean_pdf_heading(
                str(item)
            )

            if cleaned:
                result.append(cleaned)

        return result

    if isinstance(value, str) and value.strip():

        parts = re.split(
            r"\s*(?:>|/|\\)\s*",
            value.strip(),
        )

        return [
            _clean_pdf_heading(part)
            for part in parts
            if part.strip()
        ]

    return []


# ============================================================================
# DOCLING CHUNKS -> STRUCTURED HEADING DATA
# ============================================================================

def _docling_chunks_to_structured(
    chunks: list[dict],
) -> dict[str, list[str]]:
    """
    Convert Docling chunks into:

        {
            "Heading A": [
                "content...",
                "content..."
            ],
            "Heading B": [
                "content..."
            ]
        }

    This is the structure consumed by:

        build_hierarchical_chunks()

    Tables remain embedded as Markdown inside the chunk content.
    """

    structured: dict[str, list[str]] = {}

    for chunk in chunks:

        if not isinstance(chunk, dict):
            continue

        # Support both our expected HTTP format and a few common aliases.
        text = (
            chunk.get("text")
            or chunk.get("content")
            or chunk.get("body")
            or ""
        )

        text = _clean_pdf_text(
            str(text)
        )

        if not text:
            continue

        headings = _normalize_section_path(
            chunk.get("section_path")
            or chunk.get("headings")
            or chunk.get("heading_path")
            or chunk.get("section")
        )

        heading = (
            " > ".join(headings)
            if headings
            else "PDF Content"
        )

        structured.setdefault(
            heading,
            []
        ).append(text)

    return structured


# ============================================================================
# TINY CHUNK MERGING
# ============================================================================

def _merge_tiny_chunks(
    chunks: list[dict],
) -> list[dict]:
    """
    Merge very small chunks into the following chunk.

    This avoids producing retrieval fragments containing only a few tokens.
    """

    if not chunks:
        return []

    merged: list[dict] = []

    buffer: dict | None = None

    for index, original_chunk in enumerate(chunks):

        chunk = dict(original_chunk)

        if buffer is not None:

            previous_headings = (
                buffer.get("headings")
                or []
            )

            current_headings = (
                chunk.get("headings")
                or []
            )

            headings = (
                previous_headings
                or current_headings
            )

            chunk = {
                "headings": headings,
                "body": (
                    f"{buffer['body']}\n\n"
                    f"{chunk['body']}"
                ),
            }

            buffer = None

        body = str(
            chunk.get("body") or ""
        ).strip()

        chunk["body"] = body

        if (
            _chunk_token_count(body)
            < PDF_MIN_CHUNK_TOKENS
            and index != len(chunks) - 1
        ):
            buffer = chunk
            continue

        merged.append(chunk)

    if buffer is not None:

        if merged:
            merged[-1]["body"] += (
                "\n\n"
                + buffer["body"]
            )
        else:
            merged.append(buffer)

    return merged


# ============================================================================
# LOCAL DOCLING + HYBRID CHUNKER
# ============================================================================

def _local_pdf_convert_and_chunk(
    filepath: str,
) -> tuple[str, int, list[dict]]:

    logger.info(
        "[pdf] Using local Docling + HybridChunker"
    )

    result = _docling_converter.convert(
        filepath
    )

    document = result.document

    page_count = (
        len(document.pages)
        if hasattr(document, "pages")
        else 0
    )

    markdown = _clean_pdf_text(
        document.export_to_markdown()
    )

    chunker = _ensure_pdf_chunker()

    raw_chunks: list[dict] = []

    for chunk in chunker.chunk(
        dl_doc=document
    ):

        headings: list[str] = []

        for heading in (
            getattr(
                chunk.meta,
                "headings",
                None,
            )
            or []
        ):

            cleaned_heading = _clean_pdf_heading(
                heading
            )

            if cleaned_heading:
                headings.append(
                    cleaned_heading
                )

        # Remove duplicate headings while preserving order.
        headings = list(
            dict.fromkeys(headings)
        )

        body = _clean_pdf_text(
            chunk.text
        )

        if not body:
            continue

        raw_chunks.append(
            {
                "headings": headings,
                "body": body,
            }
        )

    raw_chunks = _merge_tiny_chunks(
        raw_chunks
    )

    chunks = []

    for item in raw_chunks:

        chunks.append(
            {
                "text": item["body"],
                "section_path": item["headings"],
            }
        )

    return (
        markdown,
        page_count,
        chunks,
    )


# ============================================================================
# REMOTE DOCLING CLIENT
# ============================================================================

def _remote_pdf_convert_and_chunk(
    filepath: str,
) -> tuple[str, int, list[dict]]:

    if DoclingClient is None:
        raise RuntimeError(
            "docling_client.py is not available"
        )

    logger.info(
        "[pdf] Using Docling HTTP service: %s",
        DOCLING_BASE_URL,
    )

    client = DoclingClient(
        base_url=DOCLING_BASE_URL,
        timeout=DOCLING_TIMEOUT_SECONDS,
        do_ocr=False,
    )

    data = client.convert(
        filepath,
        include_chunks=True,
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            "Docling service returned invalid JSON"
        )

    markdown = _clean_pdf_text(
        data.get("markdown", "")
    )

    chunks = data.get("chunks") or []

    if not isinstance(chunks, list):
        raise RuntimeError(
            "Docling service returned invalid chunks"
        )

    page_count_raw = (
        data.get("page_count")
        or data.get("pages")
        or 0
    )

    try:
        page_count = int(
            page_count_raw
        )
    except (TypeError, ValueError):
        page_count = 0

    if not chunks:
        raise RuntimeError(
            "Docling service returned no chunks"
        )

    return (
        markdown,
        page_count,
        chunks,
    )


# ============================================================================
# SINGLE PDF CONVERSION ENTRY POINT
# ============================================================================

def _convert_pdf_sync(
    filepath: str,
) -> tuple[str, int, list[dict], str]:
    """
    IMPORTANT:

    This is the ONLY _convert_pdf_sync function.

    Strategy:

        1. Docling HTTP service
        2. Local Docling + HybridChunker fallback
    """

    try:

        (
            markdown,
            page_count,
            chunks,
        ) = _remote_pdf_convert_and_chunk(
            filepath
        )

        return (
            markdown,
            page_count,
            chunks,
            "docling_client",
        )

    except Exception as remote_exc:

        logger.warning(
            "[pdf] Docling HTTP service failed: %s",
            remote_exc,
        )

        logger.info(
            "[pdf] Falling back to local Docling"
        )

        (
            markdown,
            page_count,
            chunks,
        ) = _local_pdf_convert_and_chunk(
            filepath
        )

        return (
            markdown,
            page_count,
            chunks,
            "local_docling_hybrid_chunker",
        )


# ============================================================================
# WEBSITE NOISE FILTER
# ============================================================================

REMOVE_HEADINGS = {
    "VIT @ Connect",
    "Other Links",
    "Quick Links",
    "VISITORS",
    "Committees @ VIT",
    "Don't Trust Fake Website/ Page / Channels",
    "BEWARE OF ILLEGAL/FAKE WEBSITES",
    "Last Updated",
    "Others",
    "Beware of VITEEE fake websites",
    "Announcements",
}


REMOVE_TEXT_CONTAINS = [
    "Campus Tour",
    "Student Login",
    "Parent Login",
    "VIT Intranet",
    "VITAA Website",
    "Last Updated:",
    "Copyrights ©",
    "Admissions Open",
    "Beware of fraudulent",
]


def is_bad_heading(
    text: str,
) -> bool:

    if not text:
        return False

    normalized = text.strip().lower()

    return any(
        heading.lower() in normalized
        for heading in REMOVE_HEADINGS
    )


# ============================================================================
# URL EXTRACTION
# ============================================================================

def _extract_structured(
    html: str,
    base_url: str,
) -> tuple[str, dict]:

    """
    Extract:

        heading -> [content]

    from HTML.

    The heading grouping is preserved specifically because it becomes:

        parent
          -> child
              -> grandchildren

    during build_hierarchical_chunks().
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title = ""

    if soup.title:
        title = soup.title.get_text(
            strip=True
        )

    # Remove obvious page chrome.
    for tag in soup.find_all(
        [
            "script",
            "style",
            "header",
            "footer",
            "nav",
            "aside",
            "noscript",
            "svg",
        ]
    ):
        tag.decompose()

    # Remove common layout containers.
    for div in soup.find_all(
        class_=lambda value:
        value
        and any(
            keyword in str(value).lower()
            for keyword in [
                "header",
                "footer",
                "menu",
                "navigation",
                "sidebar",
                "announcement",
                "breadcrumb",
                "popup",
                "newsletter",
            ]
        )
    ):
        div.decompose()

    page_data = defaultdict(list)

    parsed = urlparse(base_url)

    path_name = (
        parsed.path.rstrip("/").split("/")[-1]
        or "page"
    )

    current_heading = (
        f"{path_name} - Introduction"
    )

    # ------------------------------------------------------------------------
    # Main document-order extraction
    # ------------------------------------------------------------------------

    for elem in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "p",
            "table",
            "ul",
            "ol",
        ]
    ):

        # Heading
        if elem.name.startswith("h"):

            heading = elem.get_text(
                separator=" ",
                strip=True,
            )

            if heading:
                current_heading = heading

            continue

        if is_bad_heading(
            current_heading
        ):
            continue

        texts = [
            text.strip()
            for text in elem.stripped_strings
            if text.strip()
        ]

        links = []

        for anchor in elem.find_all(
            "a",
            href=True,
        ):

            link_text = anchor.get_text(
                " ",
                strip=True,
            )

            href = anchor.get(
                "href",
                "",
            ).strip()

            if not href:
                continue

            link_url = urljoin(
                base_url,
                href,
            )

            if (
                link_url
                and not link_url.lower().startswith(
                    "javascript:"
                )
            ):

                if link_text:
                    links.append(
                        f"{link_text} ({link_url})"
                    )
                else:
                    links.append(
                        link_url
                    )

        combined = " ".join(
            texts
        ).strip()

        if links:

            combined = (
                f"{combined} | "
                + " | ".join(links)
            ).strip()

        if not combined:
            continue

        if len(combined) < 8:
            continue

        if any(
            bad.lower()
            in combined.lower()
            for bad in REMOVE_TEXT_CONTAINS
        ):
            continue

        # Prevent duplicate content under the same heading.
        if combined not in page_data[
            current_heading
        ]:
            page_data[
                current_heading
            ].append(
                combined
            )

    # ------------------------------------------------------------------------
    # Elementor FAQ / accordion extraction
    # ------------------------------------------------------------------------

    faqs = soup.select(
        ".elementor-tab-title, "
        ".elementor-tab-content"
    )

    current_question = None

    for elem in faqs:

        classes = elem.get(
            "class",
            [],
        )

        if (
            "elementor-tab-title"
            in classes
        ):

            current_question = (
                elem.get_text(
                    " ",
                    strip=True,
                )
            )

        elif (
            "elementor-tab-content"
            in classes
        ):

            answer = elem.get_text(
                " ",
                strip=True,
            )

            if (
                current_question
                and answer
            ):

                faq_text = (
                    f"Q: {current_question} "
                    f"| A: {answer}"
                )

                if not any(
                    bad.lower()
                    in faq_text.lower()
                    for bad in REMOVE_TEXT_CONTAINS
                ):

                    if faq_text not in page_data[
                        "Frequently Asked Questions"
                    ]:

                        page_data[
                            "Frequently Asked Questions"
                        ].append(
                            faq_text
                        )

    # ------------------------------------------------------------------------
    # Final cleanup
    # ------------------------------------------------------------------------

    cleaned = {}

    for heading, content in page_data.items():

        if is_bad_heading(
            heading
        ):
            continue

        valid_content = [
            item.strip()
            for item in content
            if item
            and item.strip()
        ]

        if valid_content:
            cleaned[
                heading.strip()
            ] = valid_content

    return (
        title,
        cleaned,
    )


# ============================================================================
# STRUCTURED -> REVIEW TEXT
# ============================================================================

def _structured_to_review_text(
    structured: dict,
) -> str:

    lines = []

    for heading, items in structured.items():

        lines.append(
            f"## {heading}"
        )

        for item in items:

            lines.append(
                f"- {item}"
            )

        lines.append("")

    return "\n".join(
        lines
    ).strip()


# ============================================================================
# URL HTTP SESSION
# ============================================================================

def _build_http_session() -> requests.Session:
    """
    Requests session with retry support.

    This is intentionally synchronous because it is executed using
    asyncio.to_thread() from FastAPI.
    """

    session = requests.Session()

    retry = Retry(
        total=URL_MAX_RETRIES,
        connect=URL_MAX_RETRIES,
        read=URL_MAX_RETRIES,
        status=URL_MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=frozenset(
            ["GET"]
        ),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount(
        "http://",
        adapter,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "image/avif,"
                "image/webp,"
                "*/*;q=0.8"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
            "Cache-Control": "no-cache",
        }
    )

    return session


def _fetch_url_sync(
    url: str,
) -> requests.Response:

    session = _build_http_session()

    try:

        response = session.get(
            url,
            timeout=(
                URL_CONNECT_TIMEOUT,
                URL_READ_TIMEOUT,
            ),
            allow_redirects=True,
        )

        response.raise_for_status()

        return response

    finally:

        session.close()


# ============================================================================
# URL ENDPOINT
# ============================================================================

@router.post("/url")
async def admin_scrape_url(
    payload: dict = Body(...),
):
    """
    Fetch a webpage and return:

        title
        text
        structured
        metadata

    This endpoint does NOT ingest into MongoDB/Qdrant.
    """

    url = str(
        payload.get("url", "")
    ).strip()

    if not url:
        raise HTTPException(
            status_code=400,
            detail="url is required",
        )

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only http:// and https:// "
                "URLs are supported."
            ),
        )

    if not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL.",
        )

    logger.info(
        "[scrape] Fetching URL: %s",
        url,
    )

    try:

        response = await asyncio.to_thread(
            _fetch_url_sync,
            url,
        )

    except requests.exceptions.ConnectTimeout:

        raise HTTPException(
            status_code=504,
            detail=(
                "The target website did not "
                "accept the connection in time. "
                "The remote server may be "
                "temporarily unavailable."
            ),
        )

    except requests.exceptions.ReadTimeout:

        raise HTTPException(
            status_code=504,
            detail=(
                "The target website connected but "
                "did not return the page within "
                "the allowed time."
            ),
        )

    except requests.exceptions.SSLError as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                f"TLS/SSL error while fetching URL: "
                f"{exc}"
            ),
        )

    except requests.exceptions.RequestException as exc:

        logger.exception(
            "[scrape] URL request failed"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                f"Failed to fetch URL: {exc}"
            ),
        )

    content_type = (
        response.headers
        .get(
            "content-type",
            "",
        )
        .lower()
    )

    if (
        "text/html"
        not in content_type
        and "application/xhtml"
        not in content_type
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "URL did not return HTML "
                f"(content-type: {content_type})"
            ),
        )

    title, structured = (
        _extract_structured(
            response.text,
            url,
        )
    )

    text = _structured_to_review_text(
        structured
    )

    if not text:

        raise HTTPException(
            status_code=400,
            detail=(
                "No usable content survived "
                "extraction. The page may be "
                "JavaScript-rendered."
            ),
        )

    truncated = (
        len(text)
        > MAX_SCRAPE_CHARS
    )

    review_text = (
        text[:MAX_SCRAPE_CHARS]
        if truncated
        else text
    )

    return {
        "success": True,
        "title": title or url,
        "text": review_text,

        # IMPORTANT:
        # Return the FULL structured data.
        # Do NOT return the truncated review text
        # as the ingestion source.
        "structured": structured,

        "word_count": len(
            text.split()
        ),

        "truncated": truncated,
        "source": url,
        "section_count": len(
            structured
        ),
    }


# ============================================================================
# PREVIEW HIERARCHICAL CHUNKS
# ============================================================================

@router.post("/preview-chunks")
async def admin_scrape_preview_chunks(
    payload: dict = Body(...),
):
    """
    Input:

        {
            "url": "...",
            "structured": {
                "Heading": [
                    "content"
                ]
            }
        }

    Output:

        grandchild
        child
        parent

    This is exactly what the ingestion layer should receive.
    """

    url = str(
        payload.get("url")
        or payload.get("source")
        or ""
    ).strip()

    structured = payload.get(
        "structured"
    )

    if not url:
        raise HTTPException(
            status_code=400,
            detail="url is required",
        )

    if not isinstance(
        structured,
        dict,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "structured must be "
                "an object/dictionary"
            ),
        )

    # Normalize user-edited structured content.
    normalized_structured: dict[
        str,
        list[str],
    ] = {}

    for heading, items in structured.items():

        heading = str(
            heading
        ).strip()

        if not heading:
            continue

        if isinstance(
            items,
            str,
        ):
            items = [items]

        if not isinstance(
            items,
            list,
        ):
            continue

        clean_items = []

        for item in items:

            if item is None:
                continue

            item = str(
                item
            ).strip()

            if item:
                clean_items.append(
                    item
                )

        if clean_items:
            normalized_structured[
                heading
            ] = clean_items

    if not normalized_structured:
        raise HTTPException(
            status_code=400,
            detail=(
                "structured contains no usable "
                "heading/content data"
            ),
        )

    grandchildren, children, parent = (
        build_hierarchical_chunks(
            normalized_structured,
            url,
        )
    )

    return {
        "success": True,
        "grandchild": grandchildren,
        "child": children,
        "parent": parent,
        "counts": {
            "grandchild": len(
                grandchildren
            ),
            "child": len(
                children
            ),
            "parent": 1,
        },
    }


# ============================================================================
# PDF ENDPOINT
# ============================================================================

@router.post("/pdf")
async def admin_scrape_pdf(
    file: UploadFile = File(...),
):
    """
    Upload PDF and return extracted structured content.

    Flow:

        PDF
         ↓
        Docling HTTP
         ↓
        Hybrid chunks
         ↓
        structured heading groups
         ↓
        admin preview
         ↓
        ingestion confirmation

    If Docling HTTP is unavailable:

        PDF
         ↓
        local Docling
         ↓
        HybridChunker
    """

    filename = Path(
        file.filename
        or "upload.pdf"
    ).name

    if Path(
        filename
    ).suffix.lower() != ".pdf":

        raise HTTPException(
            status_code=400,
            detail=(
                "Only PDF files are supported."
            ),
        )

    contents = await file.read()

    if not contents:

        raise HTTPException(
            status_code=400,
            detail="Uploaded PDF is empty.",
        )

    # ------------------------------------------------------------------------
    # Write upload to temporary file.
    # ------------------------------------------------------------------------

    tmp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as tmp:

            tmp.write(contents)
            tmp.flush()

            tmp_path = tmp.name

        logger.info(
            "[pdf] Processing %s (%d bytes)",
            filename,
            len(contents),
        )

        # --------------------------------------------------------------------
        # Run blocking Docling work in worker thread.
        # --------------------------------------------------------------------

        async with _pdf_semaphore:

            (
                text,
                page_count,
                pdf_chunks,
                engine,
            ) = await asyncio.to_thread(
                _convert_pdf_sync,
                tmp_path,
            )

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "[pdf] Failed to read/chunk PDF"
        )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Failed to read/chunk PDF: "
                f"{exc}"
            ),
        )

    finally:

        if tmp_path:

            try:
                os.remove(
                    tmp_path
                )
            except OSError:
                pass

    # ------------------------------------------------------------------------
    # Validate extracted text.
    # ------------------------------------------------------------------------

    text = _clean_pdf_text(
        text
    )

    if not text:

        raise HTTPException(
            status_code=400,
            detail=(
                "No extractable text found. "
                "This may be a scanned/image-only "
                "PDF. OCR is disabled."
            ),
        )

    # ------------------------------------------------------------------------
    # Convert Docling chunks to heading groups.
    # ------------------------------------------------------------------------

    structured = (
        _docling_chunks_to_structured(
            pdf_chunks
        )
    )

    if not structured:

        raise HTTPException(
            status_code=400,
            detail=(
                "PDF was extracted but produced "
                "no usable structured chunks."
            ),
        )

    # ------------------------------------------------------------------------
    # Review text can be truncated.
    #
    # IMPORTANT:
    # structured remains COMPLETE.
    # ------------------------------------------------------------------------

    truncated = (
        len(text)
        > MAX_SCRAPE_CHARS
    )

    review_text = (
        text[:MAX_SCRAPE_CHARS]
        if truncated
        else text
    )

    # ------------------------------------------------------------------------
    # Build hierarchical preview as well.
    #
    # This allows the frontend to immediately display:
    #
    # parent
    #   child
    #      grandchild
    #
    # without needing another request.
    # ------------------------------------------------------------------------

    try:

        grandchildren, children, parent = (
            build_hierarchical_chunks(
                structured,
                filename,
            )
        )

    except Exception as exc:

        logger.exception(
            "[pdf] Failed to build hierarchy"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "PDF extraction succeeded, "
                "but hierarchical chunk creation "
                f"failed: {exc}"
            ),
        )

    # ------------------------------------------------------------------------
    # Final response.
    # ------------------------------------------------------------------------

    return {
        "success": True,

        "title": filename,
        "source": filename,

        # Human-readable review text.
        "text": review_text,

        # COMPLETE heading grouped data.
        "structured": structured,

        # Raw Docling chunks.
        "chunks": pdf_chunks,

        # Hierarchical representation.
        "grandchild": grandchildren,
        "child": children,
        "parent": parent,

        "chunk_count": sum(
            len(values)
            for values in structured.values()
        ),

        "grandchild_count": len(
            grandchildren
        ),

        "child_count": len(
            children
        ),

        "page_count": page_count,

        "word_count": len(
            text.split()
        ),

        "truncated": truncated,

        "section_count": len(
            structured
        ),

        "chunking_engine": engine,

        "chunking": {
            "max_tokens": PDF_MAX_TOKENS,
            "min_chunk_tokens": PDF_MIN_CHUNK_TOKENS,
            "table_serializer": "markdown",
        },
    }