from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from typing import BinaryIO

from app.services.extractors import (
    BaseExtractor,
    CsvExtractor,
    DocxExtractor,
    ExcelExtractor,
    HtmlExtractor,
    JsonExtractor,
    MarkdownExtractor,
    PdfExtractor,
    TxtExtractor,
)
from app.schemas.documents import ExtractedDocument
from app.services.ocr import extract_image


class ExtractionService:
    EXTENSION_MAP: dict[str, type[BaseExtractor]] = {
        ".pdf": PdfExtractor,
        ".docx": DocxExtractor,
        ".doc": DocxExtractor,
        ".md": MarkdownExtractor,
        ".markdown": MarkdownExtractor,
        ".html": HtmlExtractor,
        ".htm": HtmlExtractor,
        ".txt": TxtExtractor,
        ".csv": CsvExtractor,
        ".tsv": CsvExtractor,
        ".xlsx": ExcelExtractor,
        ".xls": ExcelExtractor,
        ".json": JsonExtractor,
        ".jsonl": JsonExtractor,
        ".xml": HtmlExtractor,
    }

    MIME_MAP: dict[str, type[BaseExtractor]] = {
        "application/pdf": PdfExtractor,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxExtractor,
        "application/msword": DocxExtractor,
        "text/markdown": MarkdownExtractor,
        "text/html": HtmlExtractor,
        "text/plain": TxtExtractor,
        "text/csv": CsvExtractor,
        "text/tab-separated-values": CsvExtractor,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelExtractor,
        "application/json": JsonExtractor,
        "application/xml": HtmlExtractor,
        "text/xml": HtmlExtractor,
    }
    IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/webp", "image/bmp"}
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}

    def extract(self, file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
        if not file_bytes:
            raise ValueError("File bytes are empty")

        ext = PurePosixPath(filename).suffix.lower()
        mime = (content_type or "").split(";")[0].strip().lower()
        if ext in self.IMAGE_EXTENSIONS or mime in self.IMAGE_MIME_TYPES:
            return extract_image(file_bytes, filename, content_type)
        extractor_class = self._resolve(ext, content_type)
        extractor = extractor_class()
        return extractor.extract(file_bytes, filename, content_type)

    def extract_file(self, file_obj: BinaryIO, filename: str, content_type: str) -> ExtractedDocument:
        data = file_obj.read()
        return self.extract(data, filename, content_type)

    def _resolve(self, extension: str, content_type: str) -> type[BaseExtractor]:
        ext_map = {k.lower(): v for k, v in self.EXTENSION_MAP.items()}
        if extension in ext_map:
            return ext_map[extension]

        mime = (content_type or "").split(";")[0].strip().lower()
        if mime in self.MIME_MAP:
            return self.MIME_MAP[mime]

        inferred, _ = mimetypes.guess_type(extension)
        if inferred:
            if inferred in self.MIME_MAP:
                return self.MIME_MAP[inferred]

        return TxtExtractor
