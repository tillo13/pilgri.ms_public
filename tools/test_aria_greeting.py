#!/usr/bin/env python3
"""
Playwright test: Full ARIA bond flow + greeting + language.

Tests against the LIVE site using real browser with session injection.
Tests both Andy (45) and Luke (112).

Safe to run: existing bond is already 'bonded', so re-entering the code
just returns the reveal (pure read, zero DB writes).

Usage:
    python tools/test_aria_greeting.py
"""

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

SITE = "https://pilgri.ms"

# Both players
ANDY = 45
LUKE = 112

PASSED = []
FAILED = []


def result(name, ok, detail=""):
    if ok:
        PASSED.append(name)
        print(f"  \u2705 {name}")
    else:
        FAILED.append((name, detail))
        print(f"  \u274c {name}: {detail}")


def get_user_info(user_id):
    """Get google_id and email from DB."""
    from utilities.postgres.core import db_cursor
    with db_cursor() as cur:
        cur.execute("SELECT google_id, email FROM pilgrim.users WHERE id = %s", (user_id,))
        return cur.fetchone()


def get_bond_tx():
    """Get the bond tx_hash for Andy+Luke."""
    from utilities.aria_bond_utils import get_user_bonds
    bonds = get_user_bonds(ANDY)
    bonded = [b for b in bonds if b.get('status') == 'bonded']
    return bonded[0]['bond_tx_hash'] if bonded else None


def forge_cookie(user_id, google_id, email, secret_key):
    """Create a valid Flask session cookie."""
    app = Flask(__name__)
    app.secret_key = secret_key
    si = SecureCookieSessionInterface()
    s = si.get_signing_serializer(app)
    return s.dumps(dict({
        '_uid': user_id,
        'google_id': google_id,
        'user_id': user_id,
        'user': {'email': email, 'name': email.split('@')[0], 'picture': ''},
    }))


def make_auth_context(browser, user_id, secret_key):
    """Create an authenticated browser context for a user."""
    info = get_user_info(user_id)
    if not info:
        return None
    cookie_val = forge_cookie(user_id, info['google_id'], info['email'], secret_key)
    ctx = browser.new_context(viewport={"width": 1280, "height": 2000})
    ctx.add_cookies([{
        "name": "session",
        "value": cookie_val,
        "domain": "pilgri.ms",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    }])
    return ctx


def test_bond_decoder(context, user_label, tx_hash):
    """Test the Signal page decoder terminal for a user.
    Enters the bond tx code and checks the response."""

    print(f"\n  SIGNAL DECODER: {user_label}")
    print(f"  {'~' * 36}")

    try:
        page = context.new_page()
        resp = page.goto(f"{SITE}/signal", wait_until="domcontentloaded", timeout=30000)
        result(f"[{user_label}] Signal page loads", resp.status == 200, f"got {resp.status}")
        if resp.status != 200:
            page.close()
            return

        # Check decoder terminal exists
        decoder_input = page.query_selector("#decoderInput")
        result(f"[{user_label}] Decoder input exists", decoder_input is not None, "No #decoderInput")

        if not decoder_input:
            page.close()
            return

        # Use JS to fill the input (avoids viewport/visibility issues in headless)
        page.evaluate(f"document.getElementById('decoderInput').value = '{tx_hash}'")
        page.evaluate("document.getElementById('decoderInput').dispatchEvent(new Event('input'))")
        typed_val = page.evaluate("document.getElementById('decoderInput').value")
        result(f"[{user_label}] Tx code entered", typed_val == tx_hash, f"input value: {typed_val[:30]}...")

        # Find and click TRANSMIT button via JS
        has_btn = page.evaluate("!!document.getElementById('decoderSubmit')")
        result(f"[{user_label}] TRANSMIT button exists", has_btn, "No #decoderSubmit")

        if has_btn:
            # Listen for the API response, click via JS
            with page.expect_response("**/api/signal/decode-tx", timeout=30000) as resp_info:
                page.evaluate("document.getElementById('decoderSubmit').click()")
            api_resp = resp_info.value
            api_status = api_resp.status
            result(f"[{user_label}] API returns 200", api_status == 200, f"got {api_status}")

            if api_status == 200:
                api_data = api_resp.json()

                # Should be recognized as a bond fragment
                is_fragment = api_data.get('is_fragment', False)
                result(f"[{user_label}] Recognized as ARIA bond", is_fragment, f"response: {str(api_data)[:100]}")

                # Bond should be complete (already bonded)
                bond_complete = api_data.get('bond_complete', False)
                already_bonded = api_data.get('already_bonded', False)
                result(f"[{user_label}] Bond shows complete/already-bonded",
                       bond_complete or already_bonded,
                       f"bond_complete={bond_complete}, already_bonded={already_bonded}")

                # Should have reveal data
                if bond_complete or already_bonded:
                    has_landmark = bool(api_data.get('landmark'))
                    has_captains = bool(api_data.get('captain_1') or api_data.get('captain_name_1'))
                    has_revelation = bool(api_data.get('aria_revelation'))
                    result(f"[{user_label}] Has landmark in response", has_landmark,
                           f"landmark={api_data.get('landmark')}")
                    result(f"[{user_label}] Has captain names", has_captains,
                           f"keys: {[k for k in api_data if 'captain' in k]}")
                    result(f"[{user_label}] Has ARIA revelation text", has_revelation,
                           f"revelation={str(api_data.get('aria_revelation', ''))[:60]}")

                    # Check no blockchain language in response
                    response_text = str(api_data).lower()
                    has_blockchain = 'blockchain' in response_text
                    result(f"[{user_label}] No 'blockchain' in API response",
                           not has_blockchain, "Found 'blockchain' in response")

                # Wait for EpicReveal overlay to appear
                page.wait_for_timeout(3000)

                # Check EpicReveal overlay exists
                er_overlay = page.query_selector('.er-overlay')
                result(f"[{user_label}] EpicReveal overlay launched", er_overlay is not None,
                       "No .er-overlay found — EpicReveal didn't launch")

                if er_overlay:
                    # Check orb is visible
                    orb_visible = page.evaluate("document.querySelector('.er-orb')?.classList.contains('visible')")
                    result(f"[{user_label}] ARIA orb visible in reveal", orb_visible,
                           "Orb not visible")

                    # Check text lines are appearing
                    line_count = page.evaluate("document.querySelectorAll('.er-line').length")
                    result(f"[{user_label}] Typed text lines appearing", line_count > 0,
                           f"line_count={line_count}")

                    # Check NO scrollbar on overlay (overflow: hidden)
                    has_scrollbar = page.evaluate("""
                        (() => {
                            const el = document.querySelector('.er-overlay');
                            return el ? el.scrollHeight > el.clientHeight : false;
                        })()
                    """)
                    overflow = page.evaluate("getComputedStyle(document.querySelector('.er-overlay')).overflow")
                    result(f"[{user_label}] No scrollbar on overlay", overflow == 'hidden',
                           f"overflow={overflow}")

                    # Check body scroll is locked
                    body_has_class = page.evaluate("document.body.classList.contains('er-active')")
                    result(f"[{user_label}] Body scroll locked", body_has_class,
                           "body missing .er-active class")

                    # Check overlay is solid black (background: #000)
                    bg = page.evaluate("getComputedStyle(document.querySelector('.er-overlay')).backgroundColor")
                    result(f"[{user_label}] Overlay is solid black", bg in ['rgb(0, 0, 0)', '#000'],
                           f"background={bg}")

                    # === CLOSE THE REVEAL ===
                    # Click the X button to close
                    page.evaluate("document.querySelector('.er-close').click()")
                    page.wait_for_timeout(1000)

                    # Check overlay is gone
                    overlay_gone = page.evaluate("!document.querySelector('.er-overlay')")
                    result(f"[{user_label}] Overlay removed after close", overlay_gone,
                           "Overlay still in DOM")

                    # Check body scroll unlocked
                    body_unlocked = page.evaluate("!document.body.classList.contains('er-active')")
                    result(f"[{user_label}] Body scroll unlocked after close", body_unlocked,
                           "body still has .er-active")

                    # Check decoder shows bond summary (not "Processing resonance")
                    decoder_text = page.evaluate("""
                        (() => {
                            const el = document.getElementById('decoderResult');
                            if (!el) return '';
                            // May be hidden by CSS class but still has content
                            return el.innerHTML || '';
                        })()
                    """)
                    has_summary = 'ARIA BOND' in decoder_text or 'aria-first-contact' in decoder_text.lower()
                    no_processing = 'processing resonance' not in decoder_text.lower()
                    result(f"[{user_label}] Decoder shows bond summary", has_summary and no_processing,
                           f"decoder html: {decoder_text[:100]}")

                    # Check ARIA chat auto-opened with bond greeting
                    page.wait_for_timeout(800)
                    aria_greeting = page.evaluate("document.getElementById('aria-chat')?.dataset?.greeting || ''")
                    has_bond_ref = 'fragment' in aria_greeting.lower() or 'resonance' in aria_greeting.lower()
                    result(f"[{user_label}] ARIA greeting set to bond message", has_bond_ref,
                           f"greeting: {aria_greeting[:80]}")

                    # Check conversation storage was cleared
                    conv_cleared = page.evaluate("!localStorage.getItem('aria_conversation_v2')")
                    result(f"[{user_label}] ARIA conversation cleared for fresh start", conv_cleared,
                           "aria_conversation_v2 still in localStorage")

        page.close()
    except Exception as e:
        result(f"[{user_label}] Decoder test", False, str(e)[:120])
        try:
            page.close()
        except Exception:
            pass


def run_tests():
    print(f"\n{'=' * 60}")
    print(f"  PLAYWRIGHT: Full ARIA Bond Test")
    print(f"  Target: {SITE}")
    print(f"  Players: Andy (#{ANDY}), Luke (#{LUKE})")
    print(f"{'=' * 60}")

    # Get bond tx hash
    print("\nSETUP")
    print("-" * 40)
    tx_hash = get_bond_tx()
    result("Bond tx_hash found", tx_hash is not None, "No bonded bond found for Andy")
    if not tx_hash:
        print("ABORT: No bond to test")
        return 1
    print(f"  Bond tx: {tx_hash[:20]}...{tx_hash[-8:]}")

    from utilities.google_auth_utils import get_secret
    secret_key = get_secret("FLASK_SECRET_KEY")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # === UNAUTHENTICATED TESTS ===
        print("\nUNAUTHENTICATED")
        print("-" * 40)
        page = browser.new_page()
        resp = page.goto(SITE, wait_until="domcontentloaded", timeout=30000)
        result("Homepage loads (200)", resp.status == 200, f"got {resp.status}")
        body = page.inner_text("body")
        result("No 'blockchain' on homepage", "blockchain" not in body.lower())
        page.close()

        # === ANDY: Bond greeting + decoder ===
        print(f"\nANDY (#{ANDY}): Bond Greeting")
        print("-" * 40)
        andy_ctx = make_auth_context(browser, ANDY, secret_key)
        if andy_ctx:
            # Check bond greeting on fresh session
            page = andy_ctx.new_page()
            raw_html = []
            page.on("response", lambda r: raw_html.append(r) if "/colony" in r.url and r.status == 200 else None)
            resp = page.goto(f"{SITE}/colony", wait_until="domcontentloaded", timeout=30000)
            result("[Andy] Colony page loads", resp.status == 200, f"got {resp.status}")

            if resp.status == 200 and raw_html:
                try:
                    body = raw_html[0].text()
                    gm = re.search(r'data-greeting="([^"]*)"', body)
                    greeting = gm.group(1).replace("&#39;", "'").replace("&amp;", "&") if gm else ""
                    has_bond = any(w in greeting.lower() for w in ["resonance", "another aria", "need to tell you"])
                    result("[Andy] Server-set bond greeting", has_bond, f"greeting: {greeting[:80]}...")
                except Exception as e:
                    result("[Andy] Server-set bond greeting", False, str(e))

                am = re.search(r'data-auto-open="([^"]*)"', body)
                auto_open = am.group(1) if am else "missing"
                result("[Andy] Auto-open is true", auto_open == "true", f"auto_open={auto_open}")

                gp = re.search(r'data-greeting-priority="([^"]*)"', body)
                priority = gp.group(1) if gp else "missing"
                result("[Andy] Greeting priority flag set", priority == "true", f"priority={priority}")
            page.close()

            # Test decoder
            test_bond_decoder(andy_ctx, "Andy", tx_hash)
            andy_ctx.close()

        # === LUKE: Bond greeting + decoder ===
        print(f"\nLUKE (#{LUKE}): Bond Greeting")
        print("-" * 40)
        luke_ctx = make_auth_context(browser, LUKE, secret_key)
        if luke_ctx:
            # Check bond greeting
            page = luke_ctx.new_page()
            raw_html = []
            page.on("response", lambda r: raw_html.append(r) if "/colony" in r.url and r.status == 200 else None)
            resp = page.goto(f"{SITE}/colony", wait_until="domcontentloaded", timeout=30000)
            result("[Luke] Colony page loads", resp.status == 200, f"got {resp.status}")

            if resp.status == 200 and raw_html:
                try:
                    body = raw_html[0].text()
                    gm = re.search(r'data-greeting="([^"]*)"', body)
                    greeting = gm.group(1).replace("&#39;", "'").replace("&amp;", "&") if gm else ""
                    has_bond = any(w in greeting.lower() for w in ["resonance", "another aria", "need to tell you"])
                    result("[Luke] Server-set bond greeting", has_bond, f"greeting: {greeting[:80]}...")
                except Exception as e:
                    result("[Luke] Server-set bond greeting", False, str(e))
            page.close()

            # Test decoder
            test_bond_decoder(luke_ctx, "Luke", tx_hash)
            luke_ctx.close()

        browser.close()

    # === SUMMARY ===
    print(f"\n{'=' * 60}")
    print(f"  \u2705 Passed:  {len(PASSED)}")
    print(f"  \u274c Failed:  {len(FAILED)}")
    if FAILED:
        print(f"\n  FAILURES:")
        for name, detail in FAILED:
            print(f"    \u2022 {name}: {detail}")
    print(f"{'=' * 60}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(run_tests())
