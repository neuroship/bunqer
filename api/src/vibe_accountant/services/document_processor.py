"""Document OCR and structured extraction using Mistral AI."""

import json
from decimal import Decimal

from mistralai import Mistral

from ..config import settings
from ..logger import logger
from .s3 import get_presigned_url

MISTRAL_OCR_MODEL = "mistral-ocr-latest"
MISTRAL_LLM_MODEL = "mistral-large-latest"

INVOICE_SCHEMA = {
    "vendor_name": "string - company/person who issued the invoice",
    "customer_name": "string - company/person the invoice is addressed to",
    "invoice_number": "string",
    "invoice_date": "string (YYYY-MM-DD)",
    "due_date": "string (YYYY-MM-DD) or null",
    "line_items": [
        {
            "description": "string",
            "quantity": "number",
            "unit_price": "number",
            "vat_rate": "number (percentage)",
            "line_total": "number",
        }
    ],
    "subtotal": "number",
    "vat_amount": "number",
    "total_amount": "number",
    "currency": "string (e.g. EUR, USD)",
    "iban": "string or null",
    "payment_reference": "string or null",
}

TAX_LETTER_SCHEMA = {
    "authority_name": "string - tax authority that sent the letter",
    "subject": "string - what the letter is about",
    "amount": "number - amount to pay or refund",
    "deadline": "string (YYYY-MM-DD) or null",
    "payment_reference": "string or null",
    "tax_period": "string - period the letter covers (e.g. Q1 2026, 2025)",
    "description": "string - brief summary of the letter content",
    "currency": "string (e.g. EUR, USD)",
}


def _get_client() -> Mistral:
    return Mistral(api_key=settings.mistral_api_key)


async def ocr_document(s3_key: str) -> str:
    """Run OCR on a document stored in S3. Returns extracted text."""
    presigned_url = get_presigned_url(s3_key, expires_in=600)
    client = _get_client()

    logger.info(f"Running OCR on {s3_key}")
    result = await client.ocr.process_async(
        model=MISTRAL_OCR_MODEL,
        document={
            "type": "document_url",
            "document_url": presigned_url,
        },
    )

    # Combine all page texts
    pages = []
    for page in result.pages:
        pages.append(page.markdown)
    text = "\n\n---\n\n".join(pages)
    logger.info(f"OCR completed for {s3_key}: {len(text)} chars")
    return text


async def extract_structured_data(ocr_text: str, doc_type: str) -> dict:
    """Use LLM to extract structured data from OCR text."""
    if doc_type == "tax_letter":
        schema = TAX_LETTER_SCHEMA
        type_label = "tax letter"
    else:
        schema = INVOICE_SCHEMA
        type_label = "sales invoice" if doc_type == "sales_invoice" else "purchase invoice"

    prompt = f"""Extract structured information from this {type_label} document.
Return ONLY valid JSON matching this schema (no markdown, no explanation):

{json.dumps(schema, indent=2)}

Document text:
---
{ocr_text}
---

Return the JSON object only."""

    client = _get_client()
    response = await client.chat.complete_async(
        model=MISTRAL_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    data = json.loads(raw)
    logger.info(f"Extracted structured data: {list(data.keys())}")
    return data


def denormalize_fields(doc, extracted: dict, doc_type: str) -> None:
    """Copy key extracted fields onto document row for search/filter."""
    if doc_type in ("sales_invoice", "purchase_invoice"):
        doc.vendor_name = extracted.get("vendor_name")
        doc.invoice_number = extracted.get("invoice_number")
        if extracted.get("invoice_date"):
            doc.invoice_date = extracted["invoice_date"]
        if extracted.get("due_date"):
            doc.due_date = extracted["due_date"]
        if extracted.get("total_amount") is not None:
            doc.total_amount = Decimal(str(extracted["total_amount"]))
        doc.payment_reference = extracted.get("payment_reference")
    elif doc_type == "tax_letter":
        doc.tax_subject = extracted.get("subject")
        if extracted.get("amount") is not None:
            doc.total_amount = Decimal(str(extracted["amount"]))
        if extracted.get("deadline"):
            doc.due_date = extracted["deadline"]
        doc.payment_reference = extracted.get("payment_reference")
        doc.vendor_name = extracted.get("authority_name")
