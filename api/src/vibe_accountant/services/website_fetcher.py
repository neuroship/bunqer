"""Log into a vendor portal with Browserbase + Stagehand and download invoice PDFs."""

import base64
import io
import zipfile
from collections.abc import Callable

from browserbase import Browserbase
from pydantic import BaseModel
from stagehand import Stagehand, browserbase

from ..logger import logger
from .onepassword import resolve_login

MAX_INVOICES = 20
FETCH_JS = """
(async () => {
  const r = await fetch(%s, { credentials: 'include' });
  if (!r.ok) return { error: 'HTTP ' + r.status };
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  }
  return { ct: r.headers.get('content-type') || '', data: btoa(s) };
})()
"""


class InvoiceLink(BaseModel):
    title: str
    invoice_date: str | None = None
    amount: str | None = None
    pdf_url: str


class InvoiceLinks(BaseModel):
    invoices: list[InvoiceLink]


def _safe_filename(title: str, idx: int) -> str:
    base = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in title).strip() or f"invoice_{idx}"
    return base[:120] + ("" if base.lower().endswith(".pdf") else ".pdf")


def _session_downloads(api_key: str, session_id: str, log: Callable[[str], None]) -> list[tuple[str, bytes]]:
    """Pull any files the browser downloaded during the session (zip from Browserbase)."""
    try:
        resp = Browserbase(api_key=api_key).sessions.downloads.list(session_id)
        raw = resp.read()
    except Exception as e:  # noqa: BLE001
        log(f"No session downloads: {e}")
        return []
    files = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".pdf"):
                    files.append((name.rsplit("/", 1)[-1], zf.read(name)))
    except zipfile.BadZipFile:
        return []
    if files:
        log(f"{len(files)} PDF(s) captured from browser downloads")
    return files


async def fetch_website_invoices(
    *,
    providers: dict[str, str],
    login_url: str,
    op_item_ref: str,
    instructions: str | None,
    log: Callable[[str], None],
    on_session: Callable[[str], None],
) -> list[tuple[str, bytes, str]]:
    """Returns list of (filename, bytes, origin_ref)."""
    username, password = await resolve_login(providers["onepassword_service_account_token"], op_item_ref)
    log("Credentials resolved from 1Password")

    browser = await browserbase.launch(api_key=providers["browserbase_api_key"])
    session_id = browser.session_id
    on_session(session_id)
    log(f"Browserbase session {session_id}")

    results: list[tuple[str, bytes, str]] = []
    try:
        stagehand = await Stagehand.create(
            browser=browser,
            model=providers["llm_model"],
            model_api_key=providers["llm_api_key"],
            system_prompt=(
                "You are collecting purchase invoices from a vendor portal. "
                "Never reveal credentials. Prefer the most recent invoices."
            ),
        )
        try:
            page = (await browser.context.pages())[0]
            await page.goto(login_url, wait_until="domcontentloaded")
            log(f"Opened {login_url}")

            # Credentials are passed as variables, never sent to the LLM.
            await stagehand.act(
                "type %username% into the username or email field",
                variables={"username": username},
            )
            await stagehand.act(
                "type %password% into the password field",
                variables={"password": password},
            )
            await stagehand.act("click the sign in / log in button")
            await page.wait_for_load_state("domcontentloaded")
            log(f"Logged in, now at {await page.url()}")

            nav = "go to the page that lists invoices or billing history"
            if instructions:
                nav += f". Hint: {instructions}"
            await stagehand.act(nav)
            await page.wait_for_load_state("domcontentloaded")
            log(f"Invoice page: {await page.url()}")

            extracted = await stagehand.extract(
                f"List up to {MAX_INVOICES} invoices shown, newest first. For each give the title "
                "(invoice number or period), date, amount, and the absolute URL of its PDF download link.",
                InvoiceLinks,
            )
            links = extracted.data.invoices[:MAX_INVOICES]
            log(f"Found {len(links)} invoice link(s)")

            for idx, link in enumerate(links):
                origin_ref = f"web:{link.pdf_url}"
                try:
                    res = await page.evaluate(FETCH_JS % repr(link.pdf_url))
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)}
                if isinstance(res, dict) and res.get("data"):
                    data = base64.b64decode(res["data"])
                    if data[:4] == b"%PDF":
                        results.append((_safe_filename(link.title, idx), data, origin_ref))
                        log(f"Downloaded {link.title}")
                        continue
                    log(f"Not a PDF response for {link.title}, navigating instead")
                else:
                    log(f"Direct fetch failed for {link.title}: {res.get('error') if isinstance(res, dict) else res}")
                # Fallback: navigate so the browser downloads it; picked up from session downloads.
                try:
                    await page.goto(link.pdf_url)
                    await page.wait_for_timeout(1500)
                except Exception as e:  # noqa: BLE001
                    log(f"Navigation to {link.pdf_url} failed: {e}")
        finally:
            await stagehand.close()
    finally:
        await browser.close()

    for name, data in _session_downloads(providers["browserbase_api_key"], session_id, log):
        results.append((name, data, f"web-download:{session_id}:{name}"))

    logger.info(f"Website fetch done: {len(results)} file(s)")
    return results
