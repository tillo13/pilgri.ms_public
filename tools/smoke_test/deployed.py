#!/usr/bin/env python3
"""
Deployed Smoke Tests - Post-deploy verification against live https://pilgri.ms
Run these after deploying to verify the production site is healthy.
"""

import requests
from . import test, TESTS, PASSED, FAILED, SKIPPED

# Production base URL
PROD_URL = "https://pilgri.ms"
TIMEOUT = 10  # seconds


# =============================================================================
# TIER 1: CRITICAL POST-DEPLOY TESTS (~10 tests)
# =============================================================================

@test("Homepage loads", tier=1, features=['api'], mode='deployed')
def test_homepage():
    # Homepage may take longer on cold start
    resp = requests.get(PROD_URL, timeout=30)
    assert resp.status_code == 200, f"Got {resp.status_code}"
    assert "Pilgrims" in resp.text or "pilgrim" in resp.text.lower(), "Missing Pilgrims branding"
    return True


@test("Static CSS loads", tier=1, features=['api'], mode='deployed')
def test_static_css():
    resp = requests.get(f"{PROD_URL}/static/css/core.css", timeout=TIMEOUT)
    assert resp.status_code == 200, f"core.css returned {resp.status_code}"
    return True


@test("Static JS loads", tier=1, features=['api'], mode='deployed')
def test_static_js():
    resp = requests.get(f"{PROD_URL}/static/js/core.js", timeout=TIMEOUT)
    assert resp.status_code == 200, f"core.js returned {resp.status_code}"
    return True


@test("Favicon loads", tier=2, features=['api'], mode='deployed')
def test_favicon():
    resp = requests.get(f"{PROD_URL}/favicon.ico", timeout=TIMEOUT)
    # Favicon may be served from different locations
    if resp.status_code == 404:
        resp = requests.get(f"{PROD_URL}/static/favicon.ico", timeout=TIMEOUT)
    if resp.status_code == 404:
        # No favicon is non-critical, just skip
        SKIPPED.append("Favicon (not configured)")
        print("  ⏭️  Favicon loads (skipped - not configured)")
        return True
    assert resp.status_code == 200, f"Favicon returned {resp.status_code}"
    return True


@test("App responds (any page)", tier=1, features=['api'], mode='deployed')
def test_app_responds():
    # Just verify the app is up and serving pages
    resp = requests.get(f"{PROD_URL}/login", timeout=TIMEOUT)
    assert resp.status_code == 200, f"App returned {resp.status_code}"
    return True


@test("Login page loads", tier=1, features=['api'], mode='deployed')
def test_login():
    resp = requests.get(f"{PROD_URL}/login", timeout=TIMEOUT)
    assert resp.status_code == 200, f"Login returned {resp.status_code}"
    return True


@test("GCS assets accessible", tier=1, features=['api'], mode='deployed')
def test_gcs_assets():
    gcs_url = "https://storage.googleapis.com/galactica-pilgrim-assets/email_assets/mars_banner_header_v2.jpg"
    try:
        resp = requests.head(gcs_url, timeout=TIMEOUT)
        assert resp.status_code == 200, f"GCS returned {resp.status_code}"
        return True
    except requests.exceptions.RequestException as e:
        SKIPPED.append("GCS assets (network error)")
        return True


@test("No 500 errors on homepage", tier=1, features=['api'], mode='deployed')
def test_no_500():
    resp = requests.get(PROD_URL, timeout=TIMEOUT)
    assert resp.status_code != 500, "Homepage returned 500 Internal Server Error"
    assert resp.status_code != 502, "Homepage returned 502 Bad Gateway"
    assert resp.status_code != 503, "Homepage returned 503 Service Unavailable"
    return True


# =============================================================================
# TIER 2: DEFAULT POST-DEPLOY TESTS
# =============================================================================

@test("Crew page loads (unauthenticated)", tier=2, features=['api', 'crew'], mode='deployed')
def test_crew_page():
    resp = requests.get(f"{PROD_URL}/crew", timeout=TIMEOUT, allow_redirects=False)
    # Should redirect to login if not authenticated
    assert resp.status_code in [200, 302, 303], f"Crew returned {resp.status_code}"
    return True


@test("Depot page loads (unauthenticated)", tier=2, features=['api', 'depot'], mode='deployed')
def test_depot_page():
    resp = requests.get(f"{PROD_URL}/depot", timeout=TIMEOUT, allow_redirects=False)
    assert resp.status_code in [200, 302, 303], f"Depot returned {resp.status_code}"
    return True


@test("Colony page loads (unauthenticated)", tier=2, features=['api', 'colony'], mode='deployed')
def test_colony_page():
    resp = requests.get(f"{PROD_URL}/colony", timeout=TIMEOUT, allow_redirects=False)
    assert resp.status_code in [200, 302, 303], f"Colony returned {resp.status_code}"
    return True


@test("Research page loads (unauthenticated)", tier=2, features=['api', 'tech'], mode='deployed')
def test_research_page():
    resp = requests.get(f"{PROD_URL}/research", timeout=TIMEOUT, allow_redirects=False)
    assert resp.status_code in [200, 302, 303], f"Research returned {resp.status_code}"
    return True


@test("Expeditions page loads (unauthenticated)", tier=2, features=['api', 'expeditions'], mode='deployed')
def test_expeditions_page():
    resp = requests.get(f"{PROD_URL}/expeditions", timeout=TIMEOUT, allow_redirects=False)
    assert resp.status_code in [200, 302, 303], f"Expeditions returned {resp.status_code}"
    return True


@test("Signal page loads (unauthenticated)", tier=2, features=['api', 'signal'], mode='deployed')
def test_signal_page():
    resp = requests.get(f"{PROD_URL}/signal", timeout=TIMEOUT, allow_redirects=False)
    assert resp.status_code in [200, 302, 303], f"Signal returned {resp.status_code}"
    return True


@test("API version endpoint", tier=2, features=['api'], mode='deployed')
def test_api_version():
    resp = requests.get(f"{PROD_URL}/api/version", timeout=TIMEOUT)
    # Version endpoint may not exist - that's OK
    if resp.status_code == 404:
        SKIPPED.append("API version (endpoint not found)")
        return True
    assert resp.status_code == 200, f"Version returned {resp.status_code}"
    return True


@test("Response headers secure", tier=2, features=['api'], mode='deployed')
def test_security_headers():
    resp = requests.get(PROD_URL, timeout=TIMEOUT)
    # Check for basic security - X-Content-Type-Options is common
    # Don't fail hard on missing headers, just note
    if 'X-Content-Type-Options' not in resp.headers:
        return "Missing X-Content-Type-Options header (non-critical)"
    return True


@test("HTTPS redirect works", tier=2, features=['api'], mode='deployed')
def test_https_redirect():
    # Request HTTP, should redirect to HTTPS
    try:
        resp = requests.get("http://pilgri.ms", timeout=TIMEOUT, allow_redirects=False)
        # Should get 301/302 redirect
        assert resp.status_code in [301, 302, 307, 308], f"HTTP returned {resp.status_code}, expected redirect"
        location = resp.headers.get('Location', '')
        assert 'https' in location.lower(), f"Redirect not to HTTPS: {location}"
        return True
    except requests.exceptions.RequestException:
        SKIPPED.append("HTTPS redirect (network error)")
        return True


# =============================================================================
# TIER 3: FULL POST-DEPLOY TESTS
# =============================================================================

@test("Admin page requires auth", tier=3, features=['api'], mode='deployed')
def test_admin_auth():
    resp = requests.get(f"{PROD_URL}/admin", timeout=TIMEOUT, allow_redirects=False)
    # Admin should redirect unauthenticated users or return 401/403
    assert resp.status_code in [302, 303, 401, 403], f"Admin returned {resp.status_code} (should require auth)"
    return True


@test("Brainstorm page loads", tier=3, features=['api'], mode='deployed')
def test_brainstorm():
    resp = requests.get(f"{PROD_URL}/brainstorm", timeout=TIMEOUT)
    assert resp.status_code == 200, f"Brainstorm returned {resp.status_code}"
    return True


@test("All main CSS files load", tier=3, features=['api'], mode='deployed')
def test_all_css():
    css_files = ['core.css', 'signal.css', 'colony.css', 'crew.css', 'depot.css']
    missing = []
    for css in css_files:
        resp = requests.get(f"{PROD_URL}/static/css/{css}", timeout=TIMEOUT)
        if resp.status_code != 200:
            missing.append(css)
    if missing:
        return f"Missing CSS: {missing}"
    return True


@test("All main JS files load", tier=3, features=['api'], mode='deployed')
def test_all_js():
    js_files = ['core.js', 'colony.js', 'crew.js', 'depot.js', 'signal.js', 'expeditions.js', 'dashboard.js']
    missing = []
    for js in js_files:
        resp = requests.get(f"{PROD_URL}/static/js/{js}", timeout=TIMEOUT)
        if resp.status_code != 200:
            missing.append(js)
    if missing:
        return f"Missing JS: {missing}"
    return True


@test("Response time acceptable", tier=3, features=['api'], mode='deployed')
def test_response_time():
    import time
    start = time.time()
    resp = requests.get(PROD_URL, timeout=TIMEOUT)
    elapsed = time.time() - start
    if elapsed > 5.0:
        return f"Homepage took {elapsed:.2f}s (>5s is slow)"
    if elapsed > 3.0:
        return f"Homepage took {elapsed:.2f}s (>3s is concerning)"
    return True


@test("Static images directory accessible", tier=3, features=['api'], mode='deployed')
def test_images_dir():
    # Try a known image
    resp = requests.get(f"{PROD_URL}/static/images/logo/marstoken_3d_bg_sq.png", timeout=TIMEOUT)
    assert resp.status_code == 200, f"Image returned {resp.status_code}"
    return True


@test("Robots.txt exists", tier=3, features=['api'], mode='deployed')
def test_robots():
    resp = requests.get(f"{PROD_URL}/robots.txt", timeout=TIMEOUT)
    # robots.txt is optional, just check for valid response
    if resp.status_code == 404:
        return "No robots.txt (optional)"
    assert resp.status_code == 200, f"robots.txt returned {resp.status_code}"
    return True


@test("Sitemap exists", tier=3, features=['api'], mode='deployed')
def test_sitemap():
    resp = requests.get(f"{PROD_URL}/sitemap.xml", timeout=TIMEOUT)
    if resp.status_code == 404:
        return "No sitemap.xml (optional)"
    assert resp.status_code == 200, f"sitemap.xml returned {resp.status_code}"
    return True
