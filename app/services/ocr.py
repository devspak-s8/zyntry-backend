from __future__ import annotations

from io import BytesIO

from app.schemas.documents import ExtractedDocument


def ocr_available() -> bool:
    try:
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def extract_image(file_bytes: bytes, filename: str, content_type: str) -> ExtractedDocument:
    """Extract text from an image when optional OCR dependencies are installed."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise ValueError("OCR is not installed. Add Pillow and pytesseract to enable image extraction.") from exc
    try:
        image = Image.open(BytesIO(file_bytes))
        text = pytesseract.image_to_string(image).strip()
    except Exception as exc:
        raise ValueError(f"Unable to OCR image: {exc}") from exc
    return ExtractedDocument(
        title=filename,
        paragraphs=[{"text": text, "metadata": {"extraction": "ocr"}}] if text else [],
        metadata={"content_type": content_type, "extraction": "ocr", "width": image.width, "height": image.height},
        source=filename,
    )
