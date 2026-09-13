"""Log into a vendor portal with Browserbase + Stagehand and download invoice PDFs."""

import base64
import io
import zipfile
from collections.abc import Callable
from datetime import date
from urllib.parse import urlparse

from browserbase import Browserbase
from pydantic import BaseModel
from stagehand import Stagehand, browserbase

from ..logger import logger
from .onepassword import resolve_login, resolve_totp

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


def _same_page(url: str, other: str) -> bool:
    a, b = urlparse(url), urlparse(other)
    return a.netloc == b.netloc and a.path.rstrip("/") == b.path.rstrip("/")


def _in_window(raw: str | None, date_from: date | None, date_to: date | None) -> bool:
    """Keep invoices whose date parses and falls in the window; keep undated ones."""
    if not raw or not (date_from or date_to):
        return True
    try:
        d = date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return True
    return (not date_from or d >= date_from) and (not date_to or d <= date_to)


async def _act(stagehand: Stagehand, log: Callable[[str], None], instruction: str, **kwargs) -> bool:
    """Run an act step; log failures and cache hits (replayed steps skip the LLM)."""
    result = await stagehand.act(instruction, **kwargs)
    cache = result.metadata.cache if result.metadata else None
    if cache and cache.status and str(cache.status).lower().endswith("hit"):
        log(f"Cached step replayed: '{instruction[:50]}'")
    if not result.data.success:
        log(f"Step failed: '{instruction}' -> {result.data.message}")
    return result.data.success


async def _settle(page, ms: int = 1500) -> None:
    """Let late scripts (cookie banners, SPA routing) finish before acting."""
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(ms)


async def _act_retry(
    stagehand: Stagehand, page, log: Callable[[str], None], instruction: str, attempts: int = 3, **kwargs
) -> bool:
    """Act, and on failure clear overlays, wait, and try again."""
    for attempt in range(1, attempts + 1):
        if await _act(stagehand, log, instruction, **kwargs):
            return True
        if attempt < attempts:
            await _dismiss_overlays(stagehand, log)
            await _settle(page)
            log(f"Retrying ({attempt + 1}/{attempts}): '{instruction[:50]}'")
    return False


async def _dismiss_overlays(stagehand: Stagehand, log: Callable[[str], None]) -> None:
    """Close a cookie consent or promo dialog if one is covering the page."""
    found = await stagehand.observe(
        "the button that accepts all cookies or closes a cookie consent / promotional dialog, "
        "only if such a dialog is currently visible"
    )
    if not found.data:
        return
    action = found.data[0]
    await stagehand.act(action)
    log(f"Dismissed dialog via: {action.description[:80]}")


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
    op_username_ref: str,
    op_password_ref: str,
    op_totp_ref: str | None,
    instructions: str | None,
    date_from: date | None = None,
    date_to: date | None = None,
    log: Callable[[str], None],
    on_session: Callable[[str], None],
) -> list[tuple[str, bytes, str]]:
    """Returns list of (filename, bytes, origin_ref)."""
    username, password = await resolve_login(
        providers["onepassword_service_account_token"], op_username_ref, op_password_ref
    )
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
            cache=True,
            self_heal=True,
        )
        try:
            page = (await browser.context.pages())[0]
            await page.goto(login_url, wait_until="domcontentloaded")
            await _settle(page)
            log(f"Opened {login_url}")
            await _dismiss_overlays(stagehand, log)

            # Credentials are passed as variables, never sent to the LLM.
            await _act_retry(
                stagehand, page, log, "type %username% into the username or email field",
                variables={"username": username},
            )
            # Two-step logins ask for the password on the next screen.
            if not (await stagehand.observe("the password input field")).data:
                await _act(stagehand, log, "click the next / continue / verder button")
                await _settle(page)
                await _dismiss_overlays(stagehand, log)
            await _act_retry(
                stagehand, page, log, "type %password% into the password field",
                variables={"password": password},
            )
            await _act_retry(stagehand, page, log, "click the sign in / log in / inloggen button")
            await _settle(page)
            log(f"Submitted login, now at {await page.url()}")

            if op_totp_ref and (await stagehand.observe("the one-time / verification code input field")).data:
                code = await resolve_totp(providers["onepassword_service_account_token"], op_totp_ref)
                await _act_retry(
                    stagehand, page, log, "type %code% into the one-time / verification code field",
                    variables={"code": code},
                )
                await _act_retry(stagehand, page, log, "click the confirm / verify / continue button")
                await _settle(page)
                log(f"Submitted 2FA code, now at {await page.url()}")
            elif op_totp_ref:
                log("No 2FA prompt shown, skipping code")

            await _dismiss_overlays(stagehand, log)
            current = await page.url()
            if _same_page(current, login_url):
                raise RuntimeError(
                    f"Login did not complete, still at {current}. Check the session replay."
                )

            nav = "go to the page that lists invoices or billing history"
            if instructions:
                nav += f". Hint: {instructions}"
            await _act(stagehand, log, nav)
            await page.wait_for_load_state("domcontentloaded")
            await _dismiss_overlays(stagehand, log)
            log(f"Invoice page: {await page.url()}")

            window = ""
            if date_from or date_to:
                window = f" Only include invoices dated between {date_from or 'the beginning'} and {date_to or 'today'}."
                await _act(
                    stagehand, log,
                    "if the page has a period or year filter for invoices, set it so that invoices"
                    f" from {date_from or 'the beginning'} to {date_to or 'today'} are shown; otherwise do nothing",
                )
            extracted = await stagehand.extract(
                f"List up to {MAX_INVOICES} invoices shown, newest first.{window} For each give the title "
                "(invoice number or period), date as YYYY-MM-DD, amount, and the absolute URL of its PDF download link.",
                InvoiceLinks,
            )
            links = [link for link in extracted.data.invoices if _in_window(link.invoice_date, date_from, date_to)]
            links = links[:MAX_INVOICES]
            log(f"Found {len(extracted.data.invoices)} invoice link(s), {len(links)} in period")

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
