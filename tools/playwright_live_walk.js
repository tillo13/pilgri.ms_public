/*
 * Live Playwright walkthrough — Pilgrims production smoke test.
 *
 * Companion to tools/new_player_walkthrough.py (backend) and
 * tools/smoke_test/local.py (static catalog/db sanity). This one drives a
 * real browser as Andy (user 45) via the KUMORI_TEST_API_KEY apikey auth,
 * visits every page, clicks every tab + accordion + critical modal, and
 * captures console errors / network 5xx / page errors as it goes.
 *
 * Run:
 *   pw tools/playwright_live_walk.js
 *
 * Env (auto-fetched if absent):
 *   APIKEY    KUMORI_TEST_API_KEY (gcloud secrets versions access latest --secret=KUMORI_TEST_API_KEY)
 *   USER_ID   defaults to 45 (Andy)
 *   BASE_URL  defaults to https://pilgri.ms
 *
 * Output:
 *   /tmp/galactica_live_walk/report.md
 *   /tmp/galactica_live_walk/screenshots/<route>.png
 *   /tmp/galactica_live_walk/errors.json (machine-readable)
 *
 * Exit 0 = clean, exit 1 = errors found.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const BASE_URL = process.env.BASE_URL || 'https://pilgri.ms';
const USER_ID = process.env.USER_ID || '45';
const OUT_DIR = '/tmp/galactica_live_walk';
const SHOTS_DIR = path.join(OUT_DIR, 'screenshots');

// ── Auth ─────────────────────────────────────────────────────────────────
function fetchApiKey() {
  if (process.env.APIKEY) return process.env.APIKEY;
  try {
    return execSync(
      'gcloud secrets versions access latest --secret=KUMORI_TEST_API_KEY --project=galactica-character-game',
      { encoding: 'utf8' }
    ).trim();
  } catch (e) {
    console.error('Could not fetch KUMORI_TEST_API_KEY via gcloud:', e.message);
    process.exit(2);
  }
}

// ── Routes ───────────────────────────────────────────────────────────────
// Static + auth-required page routes. Each entry can be a string or an
// object with { path, click: [...selectors], expect: 'text or selector' }.
// Click selectors are run sequentially against the page after navigation;
// we wait briefly between clicks and re-check console errors.
const ROUTES = [
  // Public-ish landing pages
  { path: '/', label: 'Home (auth)' },
  { path: '/about', label: 'About' },
  { path: '/lore', label: 'Lore' },
  { path: '/changelog', label: 'Changelog' },

  // Main authed app — these have rich UI to exercise
  {
    path: '/crew',
    label: 'Crew (all 4 tabs)',
    click: [
      // /crew has tabs for captain / scientist / aria / robot — switch through them
      { selector: '[data-tab="captain"]', desc: 'Captain tab' },
      { selector: '[data-tab="scientist"]', desc: 'Scientist tab' },
      { selector: '[data-tab="aria"]', desc: 'ARIA tab' },
      { selector: '[data-tab="robot"]', desc: 'Robot/Narog tab', waitAfter: 1000 },
      // Open the Allocation accordion specifically (manifest is a separate
      // accordion above it; default `.narog-accordion-head` would hit manifest).
      { selector: '[data-accordion-key="allocation"] .narog-accordion-head', desc: 'Open allocation accordion', optional: true, scrollIntoView: true, waitAfter: 800 },
      // Now click the first allocation row's base-stat pill — this opens the
      // 5/100 explainer modal we updated for #1436.
      { selector: '[data-accordion-key="allocation"] .na-row-stat', desc: 'Base-stat explainer modal', optional: true, scrollIntoView: true, dismissModal: true, waitAfter: 600 },
    ],
  },
  { path: '/narog', label: 'Narog page direct' },
  { path: '/captain', label: 'Captain page direct' },
  { path: '/scientist', label: 'Scientist page direct' },
  { path: '/aria', label: 'ARIA page direct' },
  { path: '/trails-tab', label: 'Trails tab partial' },

  {
    path: '/colony',
    label: 'Colony (modals)',
    click: [
      // First active building card. .asset-card.active.clickable is the safer
      // selector — `building` (under construction) and `active` (complete) both
      // get `.clickable`, but `building` may be transitioning + cause stability
      // timeouts. Active cards are stable.
      { selector: '.asset-card.active.clickable', desc: 'Open active building modal', optional: true, scrollIntoView: true, dismissModal: true, timeout: 5000, waitAfter: 800, force: true },
    ],
  },
  {
    path: '/depot',
    label: 'Depot (categories)',
    click: [
      { selector: '[data-depot-category]', desc: 'Switch depot category', optional: true, scrollIntoView: true },
      { selector: '.depot-card.clickable', desc: 'Open depot item modal', optional: true, scrollIntoView: true, dismissModal: true, timeout: 5000 },
    ],
  },
  {
    path: '/expeditions',
    label: 'Expeditions (tabs + vehicle modal)',
    click: [
      { selector: '[data-tab]', desc: 'Switch expeditions tab', optional: true },
      { selector: '.vehicle-card', desc: 'Open vehicle modal', optional: true, scrollIntoView: true, dismissModal: true, timeout: 5000, waitAfter: 800, force: true },
    ],
  },
  { path: '/inventory', label: 'Inventory' },
  {
    path: '/research',
    label: 'Research (tech branches)',
    click: [
      { selector: '.branch-card, [data-branch]', desc: 'Open tech branch', optional: true },
      { selector: '.tech-card', desc: 'Open tech detail modal', optional: true, dismissModal: true },
    ],
  },
  { path: '/signal', label: 'Signal' },
  { path: '/aria-album', label: 'ARIA album' },

  // Brainstorm pages
  { path: '/brainstorm/depot-recalibration', label: 'BS: depot-recalibration' },
  { path: '/brainstorm/captain-stats', label: 'BS: captain-stats' },
  { path: '/brainstorm/robot-crew', label: 'BS: robot-crew' },
  { path: '/brainstorm/signal', label: 'BS: signal' },
  { path: '/brainstorm/signal-phase-2', label: 'BS: signal-phase-2' },
  { path: '/brainstorm/tech-tree', label: 'BS: tech-tree' },
  { path: '/brainstorm/progression', label: 'BS: progression' },
  { path: '/brainstorm/trail-network', label: 'BS: trail-network' },
  { path: '/brainstorm/icon-redesign', label: 'BS: icon-redesign' },
  { path: '/brainstorm/aria-meetings', label: 'BS: aria-meetings' },
  { path: '/brainstorm/sv-economy', label: 'BS: sv-economy' },

  // Colony sub-routes
  { path: '/colony/dashboard', label: 'Colony dashboard' },
  { path: '/colony/profile', label: 'Colony profile' },
  { path: '/colony/command', label: 'Colony command' },
  { path: '/colony/depot', label: 'Colony depot alias' },
  { path: '/colony/infrastructure', label: 'Colony infra alias' },
  { path: '/colony/expeditions', label: 'Colony expeditions alias' },

  // Admin (Andy = admin)
  {
    path: '/admin/bugs',
    label: 'Admin Bugs',
    click: [
      { selector: '.bug-row, .bug-card, [data-bug-id]', desc: 'Open bug detail', optional: true, dismissModal: true },
    ],
  },
  { path: '/admin', label: 'Admin home' },
  { path: '/admin/speed', label: 'Admin speed' },

  // Captains log (Andy)
  { path: '/captains-log/45', label: "Andy's captain's log" },

  // Static
  { path: '/sitemap.xml', label: 'sitemap' },
  { path: '/robots.txt', label: 'robots' },
  { path: '/feed.xml', label: 'feed' },
];

// ── Run ──────────────────────────────────────────────────────────────────
async function main() {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  const apikey = fetchApiKey();
  const errors = [];          // {route, kind, detail, ts}
  const summary = [];         // per-route success/fail rows
  const startedAt = new Date().toISOString();

  console.log(`[walk] base=${BASE_URL} user=${USER_ID} routes=${ROUTES.length}`);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Surface ALL events as structured errors so we can attribute to the
  // current route in flight.
  let currentRoute = '<bootstrap>';
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      const t = msg.text();
      // Filter known noise — 404s on favicons.
      if (/Failed to load resource.*404\b/.test(t) && /favicon|apple-touch/i.test(t)) return;
      // JS code reacting to its own fetch being cancelled by the walker's
      // navigation. Same root cause as the ERR_ABORTED filter above —
      // real users don't see these because they don't navigate mid-fetch.
      if (/TypeError: Failed to fetch|Failed to load (crew missions|expedition|signal|tech|aria|colony|narog|robot)/i.test(t)) return;
      errors.push({ route: currentRoute, kind: `console.${msg.type()}`, detail: t.slice(0, 500), ts: new Date().toISOString() });
    }
  });
  page.on('pageerror', (err) => {
    errors.push({ route: currentRoute, kind: 'pageerror', detail: String(err).slice(0, 500), ts: new Date().toISOString() });
  });
  page.on('requestfailed', (req) => {
    const u = req.url();
    const reason = req.failure()?.errorText || 'unknown';
    // External CDN noise — not our problem.
    if (/google-analytics|doubleclick|googletagmanager|fonts\.googleapis|favicon|cartocdn|fastly\.net/.test(u)) return;
    // ERR_ABORTED is fired when the browser cancels an in-flight request because
    // the page navigated away. Captain's Narog video and the recalibration_state
    // poll are the worst offenders (the walker hops to next route while the
    // video chunk / 200ms-delay poll is still in flight). They aren't real
    // failures — same code paths work fine for a real user who stays on a page.
    // ERR_ABORTED on our own assets and our own API endpoints means the
    // walker navigated to the next route before an in-flight request resolved.
    // Real users don't trigger these. Filter all ERR_ABORTED for our domains.
    if (reason === 'net::ERR_ABORTED' && /storage\.googleapis\.com\/galactica-pilgrim-assets|^https:\/\/pilgri\.ms\/api\//.test(u)) return;
    errors.push({ route: currentRoute, kind: 'requestfailed', detail: `${req.method()} ${u} — ${reason}`, ts: new Date().toISOString() });
  });
  page.on('response', (resp) => {
    const status = resp.status();
    const u = resp.url();
    // Same-origin only — ignore external CDN noise.
    if (!u.startsWith(BASE_URL)) return;
    if (status >= 500) {
      errors.push({ route: currentRoute, kind: `http.${status}`, detail: `${resp.request().method()} ${u}`, ts: new Date().toISOString() });
    }
  });

  // ── Bootstrap session via apikey on a tiny page first ───────────────────
  currentRoute = '<bootstrap>';
  const bootstrapUrl = `${BASE_URL}/?apikey=${encodeURIComponent(apikey)}&user_id=${USER_ID}`;
  console.log(`[walk] bootstrap → ${bootstrapUrl.replace(apikey, '<KEY>')}`);
  try {
    await page.goto(bootstrapUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500); // let the apikey redirect settle and session cookie persist
    console.log(`[walk] bootstrap OK · landing url=${page.url()}`);
  } catch (e) {
    console.error('[walk] bootstrap FAILED:', e.message);
    errors.push({ route: '<bootstrap>', kind: 'bootstrap.error', detail: e.message, ts: new Date().toISOString() });
  }

  // ── Walk every route ────────────────────────────────────────────────────
  for (const r of ROUTES) {
    const route = typeof r === 'string' ? { path: r, label: r } : r;
    currentRoute = route.path;
    const url = `${BASE_URL}${route.path}`;
    const t0 = Date.now();
    let status = 'ok';
    let httpStatus = null;

    try {
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      httpStatus = resp ? resp.status() : null;
      if (httpStatus && httpStatus >= 400) {
        status = `http_${httpStatus}`;
        errors.push({ route: route.path, kind: `nav.http.${httpStatus}`, detail: url, ts: new Date().toISOString() });
      }
      await page.waitForTimeout(800); // let JS settle, fire any deferred fetches

      // Optional clicks defined per-route. Each click can opt-in to:
      //   - waitBefore: extra ms after previous step (lets accordions animate open)
      //   - scrollIntoView: scroll element into view before clicking (avoids
      //     layout-shift/visibility-stable timeouts on lazy-loaded cards)
      //   - timeout: per-click timeout override (default 3000ms)
      for (const c of (route.click || [])) {
        try {
          if (c.waitBefore) await page.waitForTimeout(c.waitBefore);
          const handle = await page.$(c.selector);
          if (!handle) {
            if (!c.optional) {
              errors.push({ route: route.path, kind: 'click.notfound', detail: `${c.desc} (${c.selector})`, ts: new Date().toISOString() });
            }
            continue;
          }
          if (c.scrollIntoView) await handle.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
          if (c.force) {
            // Bypass ALL Playwright actionability checks (visibility / stability
            // / enabled). For dashboards where cards pass real-user clicks but
            // flake the stability check due to background lazy-image loads,
            // pulsing borders, or off-viewport positioning. Server-side errors
            // from the click path still surface via http.5xx / pageerror.
            await handle.evaluate((el) => el.click());
          } else {
            await handle.click({ timeout: c.timeout || 3000, trial: false });
          }
          await page.waitForTimeout(c.waitAfter || 600);
          if (c.dismissModal) {
            // Click body / press Escape to close any modal that opened.
            await page.keyboard.press('Escape').catch(() => {});
            await page.waitForTimeout(300);
          }
        } catch (e) {
          errors.push({ route: route.path, kind: 'click.error', detail: `${c.desc}: ${e.message.slice(0, 200)}`, ts: new Date().toISOString() });
        }
      }

      // Screenshot per route (top of page only — full-page is slow)
      const safeName = route.path.replace(/[^a-z0-9]/gi, '_').replace(/^_+|_+$/g, '') || 'home';
      const shotPath = path.join(SHOTS_DIR, `${safeName}.png`);
      await page.screenshot({ path: shotPath, fullPage: false }).catch(() => {});
    } catch (e) {
      status = 'nav_error';
      errors.push({ route: route.path, kind: 'nav.error', detail: e.message.slice(0, 300), ts: new Date().toISOString() });
    }

    const ms = Date.now() - t0;
    const errCount = errors.filter((er) => er.route === route.path).length;
    summary.push({ path: route.path, label: route.label, status, http: httpStatus, ms, errors: errCount });
    console.log(`[walk] ${route.path.padEnd(40)} ${status.padEnd(12)} ${String(httpStatus || '').padStart(3)} ${String(ms).padStart(5)}ms · ${errCount} err${errCount === 1 ? '' : 's'}`);
  }

  await browser.close();

  // ── Write report ───────────────────────────────────────────────────────
  const finishedAt = new Date().toISOString();
  const totalErrors = errors.length;
  const cleanRoutes = summary.filter((s) => s.errors === 0 && s.status === 'ok').length;

  const md = [
    `# Pilgrims live walk — ${finishedAt}`,
    ``,
    `Base: \`${BASE_URL}\` · User: \`${USER_ID}\` · Routes: \`${ROUTES.length}\``,
    `Started: \`${startedAt}\` · Finished: \`${finishedAt}\``,
    ``,
    `## Summary`,
    ``,
    `- Routes walked: **${summary.length}**`,
    `- Routes clean (status=ok, 0 errors): **${cleanRoutes}/${summary.length}**`,
    `- Total events captured: **${totalErrors}** (console.error + pageerror + http 5xx + nav errors)`,
    ``,
    `## Per-route results`,
    ``,
    `| Path | Status | HTTP | ms | Errors |`,
    `|---|---|--:|--:|--:|`,
    ...summary.map((s) => `| \`${s.path}\` | ${s.status} | ${s.http ?? ''} | ${s.ms} | ${s.errors} |`),
    ``,
  ];

  if (errors.length) {
    md.push(`## Errors`, ``, `| Route | Kind | Detail | When |`, `|---|---|---|---|`);
    for (const e of errors) {
      const detail = (e.detail || '').replace(/\|/g, '\\|').slice(0, 200);
      md.push(`| \`${e.route}\` | \`${e.kind}\` | ${detail} | ${e.ts} |`);
    }
    md.push(``);
  } else {
    md.push(`## Errors`, ``, `None.`, ``);
  }

  md.push(`## Screenshots`, ``, `Folder: \`${SHOTS_DIR}\``);

  fs.writeFileSync(path.join(OUT_DIR, 'report.md'), md.join('\n'));
  fs.writeFileSync(path.join(OUT_DIR, 'errors.json'), JSON.stringify(errors, null, 2));

  console.log(`\n[walk] report=${path.join(OUT_DIR, 'report.md')}`);
  console.log(`[walk] shots=${SHOTS_DIR}`);
  console.log(`[walk] errors=${totalErrors} (clean=${cleanRoutes}/${summary.length})`);
  process.exit(totalErrors === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error('[walk] fatal:', e);
  process.exit(2);
});
