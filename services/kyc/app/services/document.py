"""
KYC Service — Document Validation Service

Handles:
  - Multipart file intake and secure S3 upload
  - OCR text extraction (AWS Textract or Google Vision)
  - Document authenticity scoring
  - Data extraction normalization
"""
import io
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings
from app.db.models import DocumentStatus, DocumentType

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class DocumentExtractionResult:
    __slots__ = ("status", "confidence_score", "extracted_data", "rejection_reason", "storage_key")

    def __init__(
        self,
        status: DocumentStatus,
        confidence_score: float | None = None,
        extracted_data: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
        storage_key: str | None = None,
    ) -> None:
        self.status           = status
        self.confidence_score = confidence_score
        self.extracted_data   = extracted_data or {}
        self.rejection_reason = rejection_reason
        self.storage_key      = storage_key


# ---------------------------------------------------------------------------
# Abstract Document Processor
# ---------------------------------------------------------------------------

class DocumentProcessor(ABC):
    @abstractmethod
    async def upload(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload file to object storage. Returns storage key."""

    @abstractmethod
    async def extract(self, storage_key: str, document_type: DocumentType) -> DocumentExtractionResult:
        """Run OCR / extraction on stored document."""


# ---------------------------------------------------------------------------
# Mock Processor (dev / CI)
# ---------------------------------------------------------------------------

class MockDocumentProcessor(DocumentProcessor):
    """
    Returns deterministic results for development.
    Files are discarded (not actually stored).
    """

    async def upload(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        # Simulate a storage key
        key = f"mock/documents/{uuid.uuid4().hex}/{filename}"
        log.debug("Mock upload: %s (%d bytes)", key, len(file_bytes))
        return key

    async def extract(self, storage_key: str, document_type: DocumentType) -> DocumentExtractionResult:
        # Simulate extraction based on doc type
        extracted: dict[str, Any] = {
            "document_type": document_type.value,
            "storage_key": storage_key,
        }

        if document_type == DocumentType.NIN:
            extracted.update({
                "nin": "12345678901",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "1990-01-15",
                "gender": "MALE",
            })
        elif document_type == DocumentType.BVN:
            extracted.update({
                "bvn": "22187654321",
                "first_name": "JOHN",
                "last_name": "DOE",
                "phone": "08012345678",
                "date_of_birth": "1990-01-15",
            })
        elif document_type == DocumentType.PASSPORT:
            extracted.update({
                "passport_number": "A12345678",
                "surname": "DOE",
                "given_names": "JOHN",
                "nationality": "NGA",
                "date_of_birth": "1990-01-15",
                "expiry_date": "2030-01-14",
                "mrz_line1": "P<NGADOE<<JOHN<<<<<<<<<<<<<<<<<<<<<<<<",
                "mrz_line2": "A123456789NGA9001151M3001141<<<<<<<<<6",
            })

        return DocumentExtractionResult(
            status=DocumentStatus.VERIFIED,
            confidence_score=0.97,
            extracted_data=extracted,
        )


# ---------------------------------------------------------------------------
# AWS Textract Processor
# ---------------------------------------------------------------------------

class TextractDocumentProcessor(DocumentProcessor):
    """
    AWS Textract-based document extraction.
    Uploads to S3 then runs Textract analysis.
    """

    def __init__(self) -> None:
        try:
            import boto3  # type: ignore[import]
            self.s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
            self.textract = boto3.client(
                "textract",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
            self.bucket = "lendkit-kyc-documents"
        except ImportError:
            raise RuntimeError("boto3 is required for Textract provider. Run: pip install boto3")

    async def upload(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        key = f"documents/{uuid.uuid4().hex}/{filename}"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=io.BytesIO(file_bytes),
            ContentType=content_type,
            ServerSideEncryption="aws:kms",  # always encrypt at rest
        )
        log.info("Uploaded document to S3: s3://%s/%s", self.bucket, key)
        return key

    async def extract(self, storage_key: str, document_type: DocumentType) -> DocumentExtractionResult:
        response = self.textract.analyze_id(
            DocumentPages=[
                {"S3Object": {"Bucket": self.bucket, "Name": storage_key}}
            ]
        )

        fields: dict[str, Any] = {}
        confidence_scores: list[float] = []

        for doc in response.get("IdentityDocuments", []):
            for field in doc.get("IdentityDocumentFields", []):
                field_type = field.get("Type", {})
                value_det  = field.get("ValueDetection", {})
                key_name   = field_type.get("Text", "")
                key_val    = value_det.get("Text", "")
                conf       = value_det.get("Confidence", 0.0)

                if key_name and key_val:
                    fields[key_name.lower().replace(" ", "_")] = key_val
                    confidence_scores.append(conf)

        avg_conf = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
        normalized_conf = avg_conf / 100.0  # Textract uses 0–100

        status = (
            DocumentStatus.VERIFIED
            if normalized_conf >= 0.75
            else DocumentStatus.REJECTED
        )

        return DocumentExtractionResult(
            status=status,
            confidence_score=round(normalized_conf, 4),
            extracted_data=fields,
            rejection_reason=(
                None if status == DocumentStatus.VERIFIED
                else f"Low confidence score: {normalized_conf:.1%}"
            ),
            storage_key=storage_key,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_document_processor() -> DocumentProcessor:
    provider = settings.document_provider
    if provider == "aws_textract":
        return TextractDocumentProcessor()
    if provider == "google_vision":
        raise NotImplementedError("Google Vision provider not yet implemented — PRs welcome!")
    return MockDocumentProcessor()
