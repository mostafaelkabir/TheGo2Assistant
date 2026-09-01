# Copyright (c) 2026 Mostafa Elkabir. Licensed under the BSD 2-Clause License.
"""PDF extraction.

Pages with a usable text layer are read directly. Pages without one are
recorded in ``ocr_pages`` rather than OCR'd here -- OCR is a paid, batched
stage that runs later against only the pages that need it.
"""

from __future__ import annotations

import logging
from typing import cast

import pymupdf

from go2.extraction.base import MIN_CHARS_PER_TEXT_PAGE, Block, Extracted

logger = logging.getLogger(__name__)


def extract_pdf(data: bytes) -> Extracted:
    """Extract text blocks from a PDF, flagging pages that need OCR.

    Args:
        data: Raw PDF bytes.

    Returns:
        Blocks for pages with a text layer, and the 1-based page numbers of
        pages that appear to be scanned.
    """
    blocks: list[Block] = []
    ocr_pages: list[int] = []

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for index, page in enumerate(doc, start=1):
            # get_text is typed as returning a union across output modes;
            # the "text" mode specifically returns str.
            text = cast("str", page.get_text("text")).strip()
            if len(text.replace(" ", "").replace("\n", "")) < MIN_CHARS_PER_TEXT_PAGE:
                ocr_pages.append(index)
                continue
            blocks.append(Block(text=text, page=index))

    if ocr_pages:
        logger.debug("%d of %d pages need OCR", len(ocr_pages), len(ocr_pages) + len(blocks))
    return Extracted(blocks=blocks, ocr_pages=ocr_pages)
