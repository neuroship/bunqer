"""Fetch PDF invoice attachments from Gmail via the Gmail API."""

import base64
import json
from datetime import date, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_QUERY = "has:attachment filename:pdf (invoice OR factuur OR receipt OR bill)"
MAX_MESSAGES = 50


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
        _client_config(client_id, client_secret, redirect_uri), scopes=SCOPES, redirect_uri=redirect_uri
    )
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> tuple[str, str]:
    """Exchange auth code for tokens. Returns (authorized_user_json, email)."""
    flow = Flow.from_client_config(
        _client_config(client_id, client_secret, redirect_uri), scopes=SCOPES, redirect_uri=redirect_uri
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return creds.to_json(), profile.get("emailAddress", "")


def _credentials(token_json: str) -> Credentials:
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def fetch_pdf_attachments(
    token_json: str,
    query: str | None,
    log,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[tuple[str, bytes, str]]:
    """Return list of (filename, bytes, origin_ref) for PDF attachments matching query.

    The date window is appended as Gmail after:/before: operators (before is exclusive).
    `log` is a callable receiving progress lines.
    """
    creds = _credentials(token_json)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    q = query or DEFAULT_QUERY
    if date_from:
        q += f" after:{date_from:%Y/%m/%d}"
    if date_to:
        q += f" before:{date_to + timedelta(days=1):%Y/%m/%d}"
    log(f"Gmail search: {q}")

    resp = service.users().messages().list(userId="me", q=q, maxResults=MAX_MESSAGES).execute()
    messages = resp.get("messages", [])
    log(f"{len(messages)} message(s) matched")

    results = []
    for m in messages:
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "(no subject)")
        for part in _walk_parts(msg.get("payload", {})):
            filename = part.get("filename") or ""
            body = part.get("body", {})
            if not filename.lower().endswith(".pdf") or not body.get("attachmentId"):
                continue
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=m["id"], id=body["attachmentId"])
                .execute()
            )
            data = base64.urlsafe_b64decode(att["data"])
            results.append((filename, data, f"gmail:{m['id']}:{filename}"))
            log(f"Attachment '{filename}' from '{subject}'")
    return results
