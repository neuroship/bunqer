"""Collect invoices from Gmail: LLM builds the search, triages matches, PDFs come from
attachments or from the email body when there is no attachment."""

import base64
import html
import json
import os
import re
from datetime import date, timedelta
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..logger import logger
from . import llm

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", SEND_SCOPE]
# Google may return extra scopes (e.g. openid); without this oauthlib raises on the mismatch.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
DEFAULT_QUERY = "(invoice OR factuur OR receipt OR bill OR bon)"
MAX_MESSAGES = 100


# --- OAuth ---


def _client_config(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_auth_url(client_id: str, client_secret: str, redirect_uri: str, state: str) -> str:
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri), scopes=SCOPES, redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> tuple[str, str]:
    """Exchange auth code for tokens. Returns (authorized_user_json, email)."""
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri), scopes=SCOPES, redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return creds.to_json(), profile.get("emailAddress", "")


def _service(token_json: str):
    # Use the scopes Google actually granted (stored in the token), not SCOPES: tokens issued
    # before the send scope was added would fail to refresh if we claimed it.
    creds = Credentials.from_authorized_user_info(json.loads(token_json))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def can_send(token_json: str) -> bool:
    """Whether the stored grant includes permission to send mail."""
    return SEND_SCOPE in (json.loads(token_json).get("scopes") or [])


# --- Query building ---


def _date_operators(date_from: date | None, date_to: date | None) -> str:
    parts = []
    if date_from:
        parts.append(f"after:{date_from:%Y/%m/%d}")
    if date_to:
        parts.append(f"before:{date_to + timedelta(days=1):%Y/%m/%d}")
    return " ".join(parts)


async def build_query(providers: dict[str, str], description: str) -> str:
    """Turn 'Tesla charging invoices' into a Gmail search expression (without date operators)."""
    prompt = f"""Write a Gmail search query that finds emails matching this request:

"{description}"

Rules:
- Use Gmail search syntax only (from:, subject:, OR, parentheses, quotes). No date operators.
- Be inclusive: the results are filtered afterwards, so prefer recall over precision.
- Include likely sender domains and both English and Dutch words (invoice, factuur, receipt, bon, betaling).
- Do not require has:attachment.
Return JSON only: {{"query": "..."}}"""
    data = await llm.ask_json(providers, prompt)
    query = (data.get("query") or "").strip() if isinstance(data, dict) else ""
    return query or DEFAULT_QUERY


# --- Message listing and triage ---


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def _pdf_parts(msg: dict) -> list[dict]:
    return [
        p for p in _walk_parts(msg.get("payload", {}))
        if (p.get("filename") or "").lower().endswith(".pdf") and p.get("body", {}).get("attachmentId")
    ]


def list_candidates(token_json: str, query: str, date_from: date | None, date_to: date | None) -> list[dict]:
    """Messages matching the query in the window, with the fields needed for triage."""
    service = _service(token_json)
    q = f"{query} {_date_operators(date_from, date_to)}".strip()
    resp = service.users().messages().list(userId="me", q=q, maxResults=MAX_MESSAGES).execute()
    out = []
    for m in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        out.append({
            "id": m["id"],
            "subject": _header(msg, "subject") or "(no subject)",
            "from": _header(msg, "from"),
            "date": _header(msg, "date"),
            "snippet": msg.get("snippet", ""),
            "pdf_count": len(_pdf_parts(msg)),
            "_msg": msg,
        })
    return out


async def triage(providers: dict[str, str], description: str, candidates: list[dict]) -> list[dict]:
    """Ask the LLM which candidates are actually invoices/receipts for the request."""
    if not candidates:
        return []
    listing = "\n".join(
        f"{i}. from: {c['from']} | subject: {c['subject']} | date: {c['date']} | "
        f"pdf attachments: {c['pdf_count']} | snippet: {c['snippet'][:160]}"
        for i, c in enumerate(candidates)
    )
    prompt = f"""The user wants to collect: "{description}".
Below are emails that matched a broad search. Select the ones that are an invoice, receipt or
payment confirmation for that request (not newsletters, reminders, marketing or unrelated mail).

{listing}

Return JSON only: {{"selected": [<index>, ...]}}"""
    data = await llm.ask_json(providers, prompt)
    idx = data.get("selected", []) if isinstance(data, dict) else []
    chosen = []
    for i in idx:
        try:
            chosen.append(candidates[int(i)])
        except (ValueError, IndexError):
            continue
    return chosen


# --- Turning a message into PDFs ---


def _body_text(msg: dict) -> str:
    """Prefer text/plain, fall back to stripped text/html."""
    plain, html_body = "", ""
    for p in _walk_parts(msg.get("payload", {})):
        data = p.get("body", {}).get("data")
        if not data:
            continue
        text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if p.get("mimeType") == "text/plain" and not plain:
            plain = text
        elif p.get("mimeType") == "text/html" and not html_body:
            html_body = text
    if plain.strip():
        return plain
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_body, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def _email_to_pdf(msg: dict) -> bytes:
    """Render an email (headers + body text) as a simple PDF so OCR/extraction can read it."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    header = (
        f"From: {_header(msg, 'from')}\nTo: {_header(msg, 'to')}\nDate: {_header(msg, 'date')}\n"
        f"Subject: {_header(msg, 'subject')}\n\n"
    )
    text = (header + _body_text(msg)).encode("latin-1", errors="replace").decode("latin-1")
    pdf.multi_cell(0, 5, text)
    return bytes(pdf.output())


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip()[:100] or "email"


def download_selected(token_json: str, selected: list[dict], log) -> list[tuple[str, bytes, str]]:
    """(filename, bytes, origin_ref) for each selected message: attachments, else rendered body."""
    service = _service(token_json)
    results = []
    for c in selected:
        msg = c["_msg"]
        parts = _pdf_parts(msg)
        if parts:
            for p in parts:
                att = (
                    service.users().messages().attachments()
                    .get(userId="me", messageId=c["id"], id=p["body"]["attachmentId"]).execute()
                )
                results.append((p["filename"], base64.urlsafe_b64decode(att["data"]), f"gmail:{c['id']}:{p['filename']}"))
                log(f"Attachment '{p['filename']}' from '{c['subject']}'")
        else:
            results.append((_safe(c["subject"]) + ".pdf", _email_to_pdf(msg), f"gmail:{c['id']}:body"))
            log(f"No attachment, rendered email body: '{c['subject']}'")
    return results


async def preview(
    providers: dict[str, str], token_json: str, description: str | None, raw_query: str | None,
    date_from: date | None, date_to: date | None,
) -> dict:
    """What a run would do: the query used and the emails it would take."""
    query = raw_query.strip() if raw_query and raw_query.strip() else await build_query(providers, description or "invoices")
    import asyncio

    candidates = await asyncio.to_thread(list_candidates, token_json, query, date_from, date_to)
    selected = await triage(providers, description or "invoices and receipts", candidates)
    chosen_ids = {c["id"] for c in selected}
    return {
        "query": f"{query} {_date_operators(date_from, date_to)}".strip(),
        "messages": [
            {k: v for k, v in c.items() if k != "_msg"} | {"selected": c["id"] in chosen_ids}
            for c in candidates
        ],
    }


async def fetch_invoices(
    providers: dict[str, str], token_json: str, description: str | None, raw_query: str | None,
    date_from: date | None, date_to: date | None, log,
) -> list[tuple[str, bytes, str]]:
    import asyncio

    query = raw_query.strip() if raw_query and raw_query.strip() else await build_query(providers, description or "invoices")
    log(f"Gmail search: {query} {_date_operators(date_from, date_to)}")
    candidates = await asyncio.to_thread(list_candidates, token_json, query, date_from, date_to)
    log(f"{len(candidates)} email(s) matched")
    selected = await triage(providers, description or "invoices and receipts", candidates)
    log(f"{len(selected)} selected as invoices")
    files = await asyncio.to_thread(download_selected, token_json, selected, log)
    logger.info(f"Gmail fetch done: {len(files)} file(s)")
    return files


# --- Sending ---

# Gmail rejects messages over 25 MB; base64 inflates attachments by a third, so stay well under.
MAX_ATTACHMENTS_BYTES = 17 * 1024 * 1024


def _batches(files: list[tuple[str, bytes, str]]) -> list[list[tuple[str, bytes, str]]]:
    batches: list[list[tuple[str, bytes, str]]] = [[]]
    size = 0
    for f in files:
        if batches[-1] and size + len(f[1]) > MAX_ATTACHMENTS_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(f)
        size += len(f[1])
    return batches


def send_files(token_json: str, to: str, subject: str, body: str, files: list[tuple[str, bytes, str]]) -> int:
    """Email (filename, bytes, content_type) files as attachments, split over several messages
    when they exceed Gmail's size limit. Returns the number of messages sent."""
    service = _service(token_json)
    batches = _batches(files)
    for i, batch in enumerate(batches, 1):
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject if len(batches) == 1 else f"{subject} ({i}/{len(batches)})"
        msg.set_content(body)
        for filename, data, content_type in batch:
            maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info(f"Sent {len(files)} file(s) to {to} in {len(batches)} message(s)")
    return len(batches)
