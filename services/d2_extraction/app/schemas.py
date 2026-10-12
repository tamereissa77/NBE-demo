"""
documents.py — Shared Pydantic data models for the NBE RAG pipeline.

These models are the contract between:
  - extraction_service  (produces PageResult)
  - indexing_service    (consumes PageResult, produces ChunkRecord)
  - rag_service         (consumes ChunkRecord metadata at query time via Milvus)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    FIGURE = "figure"
    LIST = "list"
    UNKNOWN = "unknown"


class BBox(BaseModel):
    """Bounding box in original image pixel coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int

    def as_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, coords: list[int | float]) -> "BBox":
        return cls(x1=round(coords[0]), y1=round(coords[1]), x2=round(coords[2]), y2=round(coords[3]))


class Block(BaseModel):
    """A single layout block extracted from a page image."""

    block_id: str = Field(description="Unique ID: {doc_id}_p{page_num:03d}_b{idx:02d}")
    block_type: BlockType = BlockType.TEXT
    text: str = ""
    bbox: BBox | None = None
    confidence: float | None = None
    language: str = "ar"
    table_data: str | None = Field(
        default=None,
        description="HTML table string when block_type=table; None otherwise.",
    )
    crop_path: str | None = Field(
        default=None,
        description="Relative path to the crop PNG inside the shared volume.",
    )


class PageResult(BaseModel):
    """Full extraction result for one page — output contract of extraction_service."""

    doc_id: str
    doc_name: str
    doc_type: str  # "SOP" | "Legal Circular" | ...
    page_num: int
    original_size: tuple[int, int] = Field(description="(width, height) in pixels")
    inference_size: tuple[int, int] = Field(description="(width, height) used for model inference")
    page_image_path: str = Field(description="Relative path to the source page PNG")
    extraction_timestamp: str
    blocks: list[Block] = []


class ChunkRecord(BaseModel):
    """
    A retrieval-ready chunk — the unit that gets embedded and stored in Milvus.
    Produced by indexing_service; metadata surfaced by rag_service in citations.
    """

    chunk_id: str
    doc_id: str
    doc_name: str
    doc_type: str
    page_num: int
    block_id: str
    block_type: BlockType
    raw_text: str
    enriched_text: str = Field(description="Header-prefixed text used for embedding")
    language: str = "ar"
    bbox: list[int] | None = None
    crop_path: str | None = None
    crop_minio_url: str | None = None
    page_image_minio_url: str | None = None
    ingest_timestamp: str
    token_count: int | None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
