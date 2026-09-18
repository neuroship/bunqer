"""Log into a vendor portal with Browserbase + Stagehand and download invoice PDFs."""

import asyncio
import base64
import hashlib
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
MAX_LOAD_MORE = 10
MAX_NAV_STEPS = 6
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
    pdf_url: str | None = None


class InvoiceLinks(BaseModel):
    invoices: list[InvoiceLink]


MONTHS = {
    m: i + 1
    for i, names in enumerate([
        ("jan", "januari", "january"), ("feb", "februari", "february"), ("mrt", "maart", "mar", "march"),
        ("apr", "april"), ("mei", "may"), ("jun", "juni", "june"), ("jul", "juli", "july"),
        ("aug", "augustus", "august"), ("sep", "sept", "september"), ("okt", "oktober", "oct", "october"),
        ("nov", "november"), ("dec", "december"),
    ])
    for m in names
}


def _parse_date(raw: str | None) -> date | None:
    """Accept ISO dates plus '04 september 2026' / '4 sep 2026' style strings."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    parts = text.replace(",", " ").split()
    if len(parts) >= 3 and parts[0].isdigit() and parts[2].isdigit():
        month = MONTHS.get(parts[1].lower().rstrip("."))
        if month:
            return date(int(parts[2]), month, int(parts[0]))
    return None


def _same_page(url: str, other: str) -> bool:
    a, b = urlparse(url), urlparse(other)
    return a.netloc == b.netloc and a.path.rstrip("/") == b.path.rstrip("/")


def _in_window(raw: str | None, date_from: date | None, date_to: date | None) -> bool:
    """Keep invoices whose date parses and falls in the window; keep undated ones."""
    if not (date_from or date_to):
        return True
    d = _parse_date(raw)
    if d is None:
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
    elif result.data.action_description:
        log(f"Did: {result.data.action_description[:100]}")
    return result.data.success


UNHIDE_JS = """
(() => {
  let fixed = 0;
  for (const el of document.querySelectorAll('input, button, a, select, textarea')) {
    const r = el.getBoundingClientRect();
    if (!el.offsetParent || r.width === 0 || r.height === 0) continue;
    for (let n = el; n; n = n.parentElement) {
      if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') { n.removeAttribute('aria-hidden'); fixed++; }
      if (n.hasAttribute && n.hasAttribute('inert')) { n.removeAttribute('inert'); fixed++; }
    }
  }
  return fixed;
})()
"""

FILL_JS = """
(({ kind, value }) => {
  const visible = (el) => el.offsetParent && el.getBoundingClientRect().width > 0;
  const sel = {
    username: 'input[type=email], input[autocomplete=username], input[autocomplete=email], '
      + 'input[type=text][name*=user i], input[type=text][name*=mail i], input[type=text][id*=user i], '
      + 'input[type=text][id*=mail i], input[type=tel], input[type=text]',
    password: 'input[type=password]',
    code: 'input[autocomplete=one-time-code], input[inputmode=numeric], input[name*=code i], '
      + 'input[id*=code i], input[name*=otp i], input[id*=otp i], input[type=tel], input[type=text]',
  }[kind];
  const el = [...document.querySelectorAll(sel)].find(visible);
  if (!el) return null;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  el.focus();
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return el.id || el.name || el.type;
})
"""

SUBMIT_JS = """
(() => {
  const visible = (el) => el.offsetParent && el.getBoundingClientRect().width > 0;
  const active = document.activeElement;
  const form = active && active.form;
  const btn = [...document.querySelectorAll('button[type=submit], input[type=submit], button')]
    .filter(visible)
    .find(b => (form ? b.form === form : true) && /log|sign|inlog|verder|next|continue|confirm|verify|bevestig/i.test(b.innerText + ' ' + b.value));
  if (btn) { btn.click(); return 'click:' + (btn.innerText || btn.value).trim().slice(0, 30); }
  if (form && form.requestSubmit) { form.requestSubmit(); return 'requestSubmit'; }
  return null;
})()
"""


async def _settle(page, ms: int = 1500) -> None:
    """Let late scripts finish, then expose visually shown controls that sites hide from the a11y tree."""
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(ms)
    try:
        await page.evaluate(UNHIDE_JS)
    except Exception:  # noqa: BLE001
        pass


async def _fill_fallback(page, log: Callable[[str], None], kind: str, value: str) -> bool:
    """Deterministic DOM fill when the agent cannot locate the field."""
    try:
        target = await page.evaluate(f"({FILL_JS})({{kind: {kind!r}, value: {value!r}}})")
    except Exception as e:  # noqa: BLE001
        log(f"Fallback fill for {kind} errored: {e}")
        return False
    if target:
        log(f"Filled {kind} via DOM fallback ({target})")
        return True
    log(f"Fallback fill: no visible {kind} field")
    return False


async def _submit_fallback(page, log: Callable[[str], None]) -> bool:
    try:
        how = await page.evaluate(SUBMIT_JS)
    except Exception as e:  # noqa: BLE001
        log(f"Fallback submit errored: {e}")
        return False
    if how:
        log(f"Submitted via DOM fallback ({how})")
        return True
    return False


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


def _new_downloads(api_key: str, session_id: str, seen: set[str]) -> list[tuple[str, bytes]]:
    """Session downloads not yet in `seen`; marks them seen. Keyed by name + content hash."""
    fresh = []
    for name, data in _read_downloads_zip(api_key, session_id):
        key = f"{name}:{hashlib.sha256(data).hexdigest()}"
        if key not in seen:
            seen.add(key)
            fresh.append((name, data))
    return fresh


async def _wait_for_new_download(
    api_key: str, session_id: str, seen: set[str], attempts: int = 5, delay: float = 3.0
) -> tuple[str, bytes] | None:
    """Poll Browserbase until one file the previous clicks did not produce shows up.

    Browserbase syncs downloads with a delay, so pairing a click with its file means
    waiting for exactly one new entry before the next click.
    """
    for _ in range(attempts):
        await asyncio.sleep(delay)
        fresh = await asyncio.to_thread(_new_downloads, api_key, session_id, seen)
        if fresh:
            return fresh[0]
    return None


def _read_downloads_zip(api_key: str, session_id: str) -> list[tuple[str, bytes]]:
    try:
        resp = Browserbase(api_key=api_key).sessions.downloads.list(session_id)
        raw = resp.read()
    except Exception:  # noqa: BLE001
        return []
    files = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in sorted(zf.namelist()):
                data = zf.read(name)
                if data[:4] == b"%PDF":
                    files.append((name.rsplit("/", 1)[-1], data))
    except zipfile.BadZipFile:
        return []
    return files


EXTRACT_PROMPT = (
    "List every invoice row currently shown on this page, newest first, regardless of date. "
    "For each give the title (invoice number, product or period), the invoice date converted "
    "to YYYY-MM-DD, the amount, and the absolute URL of its PDF if the row links directly to a "
    "file (otherwise leave pdf_url empty). Return an empty list if this page shows no invoices."
)


async def _navigate_to_invoices(
    stagehand: Stagehand, page, log: Callable[[str], None], instructions: str | None
) -> list[InvoiceLink]:
    """Click through the portal until a page with invoice rows is found; raise if none within budget."""
    hint = f" Hint: {instructions}" if instructions else ""
    tried: list[str] = []
    for step in range(MAX_NAV_STEPS):
        rows = (await stagehand.extract(EXTRACT_PROMPT, InvoiceLinks)).data.invoices
        if rows:
            log(f"Invoice page: {await page.url()}")
            return rows
        if step == 0:
            prompt = f"go to the page that lists invoices or billing history.{hint}"
        else:
            prompt = (
                "This page does not list invoices. You are looking for the page with the invoice or billing "
                f"history. Previous clicks did not reach it: {'; '.join(tried)}. Click the next most likely "
                "navigation item instead, such as Billing, Invoices, Facturen, Payments, Orders, Account or "
                f"My account, expanding a collapsed menu group first if the item is inside one.{hint}"
            )
        result = await stagehand.act(prompt)
        desc = (result.data.action_description or result.data.message or "").strip()
        tried.append(desc[:80] or f"step {step + 1}")
        log(f"Navigation step {step + 1}: {desc[:100] or 'no action'}")
        await _settle(page)
        await _dismiss_overlays(stagehand, log)
    raise RuntimeError(
        f"Could not find the invoice page after {MAX_NAV_STEPS} steps, ended at {await page.url()}. "
        "Add a hint in the source instructions or check the session replay."
    )


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
            if not await _act_retry(
                stagehand, page, log, "type %username% into the username or email field",
                variables={"username": username},
            ):
                await _fill_fallback(page, log, "username", username)
            # Two-step logins ask for the password on the next screen.
            if not (await stagehand.observe("the password input field")).data:
                if await _act(stagehand, log, "click the next / continue / verder button"):
                    await _settle(page)
                    await _dismiss_overlays(stagehand, log)
            if not await _act_retry(
                stagehand, page, log, "type %password% into the password field",
                variables={"password": password},
            ):
                await _fill_fallback(page, log, "password", password)
            if not await _act_retry(stagehand, page, log, "click the sign in / log in / inloggen button"):
                await _submit_fallback(page, log)
            await _settle(page)
            log(f"Submitted login, now at {await page.url()}")

            if op_totp_ref and (
                (await stagehand.observe("the one-time / verification code input field")).data
                or await page.evaluate("!!document.querySelector('input[autocomplete=one-time-code]')")
            ):
                code = await resolve_totp(providers["onepassword_service_account_token"], op_totp_ref)
                if not await _act_retry(
                    stagehand, page, log, "type %code% into the one-time / verification code field",
                    variables={"code": code},
                ):
                    await _fill_fallback(page, log, "code", code)
                if not await _act_retry(stagehand, page, log, "click the confirm / verify / continue button"):
                    await _submit_fallback(page, log)
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

            rows = await _navigate_to_invoices(stagehand, page, log, instructions)

            # Load older rows until the window start is covered (or nothing more to load).
            for _ in range(MAX_LOAD_MORE):
                dates = [d for d in (_parse_date(r.invoice_date) for r in rows) if d]
                if not date_from or (dates and min(dates) <= date_from):
                    break
                more = await stagehand.observe(
                    "a 'show more', 'load more', 'toon meer', 'older invoices' or next-page control for the invoice list"
                )
                if not more.data:
                    log(f"No more rows to load; oldest visible invoice is {min(dates) if dates else 'unknown'}")
                    break
                await stagehand.act(more.data[0])
                await _settle(page)
                log(f"Loaded more invoice rows (oldest so far {min(dates) if dates else 'unknown'})")
                rows = (await stagehand.extract(EXTRACT_PROMPT, InvoiceLinks)).data.invoices

            links = [r for r in rows if _in_window(r.invoice_date, date_from, date_to)][:MAX_INVOICES]
            log(f"Found {len(rows)} invoice row(s), {len(links)} in period")
            if not links:
                raise RuntimeError(
                    f"No invoices between {date_from} and {date_to} on {await page.url()} "
                    f"({len(rows)} row(s) visible). Check the session replay."
                )

            clicked: list[InvoiceLink] = []
            seen: set[str] = set()  # download keys already paired or stored
            for idx, link in enumerate(links):
                label = f"{link.title} ({link.invoice_date or 'no date'}, {link.amount or 'no amount'})"
                if link.pdf_url:
                    origin_ref = f"web:{link.pdf_url}"
                    try:
                        res = await page.evaluate(FETCH_JS % repr(link.pdf_url))
                    except Exception as e:  # noqa: BLE001
                        res = {"error": str(e)}
                    if isinstance(res, dict) and res.get("data"):
                        data = base64.b64decode(res["data"])
                        if data[:4] == b"%PDF":
                            results.append((_safe_filename(link.title, idx), data, origin_ref))
                            log(f"Downloaded {label}")
                            continue
                    log(f"Direct fetch failed for {label}, trying a click")
                ok = await _act(
                    stagehand, log,
                    f"click the download (PDF) button or link of the invoice row for {label}",
                )
                if not ok:
                    ok = await _act(stagehand, log, f"click the view/open button of the invoice row for {label}")
                if ok:
                    clicked.append(link)
                    log(f"Clicked download for {label}")
                    fresh = await _wait_for_new_download(providers["browserbase_api_key"], session_id, seen)
                    if fresh:
                        results.append((
                            _safe_filename(link.title, idx), fresh[1],
                            f"web:{login_url}:{link.invoice_date}:{link.amount}:{link.title}",
                        ))
                        log(f"Downloaded {label}")
                    else:
                        log(f"No new file appeared for {label}; will store it unpaired if it shows up later")

            if clicked:
                await asyncio.sleep(4)
                stragglers = _new_downloads(providers["browserbase_api_key"], session_id, seen)
                for idx, (name, data) in enumerate(stragglers):
                    results.append((_safe_filename(name, idx), data, f"web-download:{session_id}:{name}"))
                if stragglers:
                    log(f"{len(stragglers)} late file(s) stored without pairing")
                log(f"{len(results)} PDF(s) captured from browser downloads")
        finally:
            await stagehand.close()
    finally:
        await browser.close()

    logger.info(f"Website fetch done: {len(results)} file(s)")
    return results
