"""Tests for turning attachment-less invoice emails (e.g. Apple receipts) into PDFs."""

import base64
import io
import pathlib
import sys

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def gmail_fetcher():
    for name in list(sys.modules):
        if name.startswith("vibe_accountant"):
            del sys.modules[name]
    from vibe_accountant.services import gmail_fetcher

    return gmail_fetcher


def _msg(parts: list[tuple[str, str]], subject="Your receipt from Apple.") -> dict:
    return {
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Apple <no_reply@email.apple.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Fri, 5 Sep 2026 10:05:22 +0000"},
                {"name": "Subject", "value": subject},
            ],
            "parts": [
                {"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}
                for mime, body in parts
            ],
        }
    }


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_html_only_apple_receipt_becomes_readable_pdf(gmail_fetcher):
    html = (FIXTURES / "apple_receipt.html").read_text()
    text = _pdf_text(gmail_fetcher._email_to_pdf(_msg([("text/html", html)])))

    assert "Subject: Your receipt from Apple." in text
    for needle in ("Invoice", "MT57V97H3W", "AirConsole Hero (Annual)", "EUR 23,99", "IE9700053D"):
        assert needle in text
    # no stylesheet, no image tags, no HTML comments leak into the document
    assert "custom-wwmbjm" not in text
    assert "mzstatic" not in text


def test_plain_text_still_used_when_no_html(gmail_fetcher):
    text = _pdf_text(gmail_fetcher._email_to_pdf(_msg([("text/plain", "Total: € 9,99\nThanks")])))
    assert "Total: EUR 9,99" in text


def test_render_error_falls_back_to_text(gmail_fetcher, monkeypatch):
    from fpdf import FPDF

    def boom(self, *a, **kw):
        raise ValueError("unsupported markup")

    monkeypatch.setattr(FPDF, "write_html", boom)
    pdf = gmail_fetcher._email_to_pdf(_msg([("text/html", "<p>Amount <b>€ 5,00</b></p>")]))
    assert "Amount EUR 5,00" in _pdf_text(pdf)
