"""
Generate codemap.json — a machine-readable index of the codebase.
PilgrimBot reads this to find which files to query for a given question.
Auto-runs on every deploy via the deploy tool.

Usage: python3 -m tools.generate_codemap
"""

import ast
import json
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "codemap.json")

# Only index code files (matches public repo filter)
CODE_EXTS = {".py", ".js", ".css", ".html", ".md"}

# Manual descriptions for files where auto-extraction falls short
MANUAL_DESCRIPTIONS = {
    # JS files (no docstrings, comments are terse)
    "static/js/core.js": "Shared JS utilities — $(), showToast(), formatCountdown(), MarsModal, nav prefetch, balance display, tab switching",
    "static/js/colony.js": "Colony page — discoveries grid, equipment list, asset management, activity feed tabs",
    "static/js/colony-discoveries.js": "Colony discovery cards — grid rendering, extraction, claiming, storage display",
    "static/js/colony-modals.js": "Colony item modals — detailed stats popups for discoveries, equipment, infrastructure",
    "static/js/dashboard.js": "Home/Mission Control — income display, effective rate breakdown, base total, mining drone bonus, harvest button, discovery alerts",
    "static/js/expeditions.js": "Mars map — Leaflet map, landmark pins, expedition launch, fog-of-war, vehicle selection",
    "static/js/expeditions-launch.js": "Expedition launch flow — destination picker, cost preview, vehicle select, confirmation",
    "static/js/expeditions-tracking.js": "Active expedition tracking — progress bars, ETAs, return countdowns",
    "static/js/expeditions-rewards.js": "Expedition rewards — discovery claim UI, extraction, shard payouts",
    "static/js/expeditions-page.js": "Expeditions page controller — tab switching between map, active, completed",
    "static/js/expeditions-origin.js": "Origin Sites UI — Signal ARG decoder results, site claims display",
    "static/js/depot.js": "Depot page — shop tabs, upgrade purchase, infrastructure building, commander services",
    "static/js/depot-shop.js": "Depot shop tab — equipment cards, buy buttons, affordability checks",
    "static/js/depot-xeno.js": "Xenobiology Lab — experiment UI, research point spending, stat boost display",
    "static/js/crew.js": "Crew page — captain stats, image/video management, SV ticker, asset reroll/transmute",
    "static/js/crew-missions.js": "Crew trail missions — send captain/scientist/ARIA on trails, countdown timers",
    "static/js/crew-map.js": "Crew trail map — visual trail progress toward landmarks",
    "static/js/crew-notifications.js": "Crew notification badges — unread counts, mission completion alerts",
    "static/js/aria.js": "ARIA chat widget — floating orb, chat window, SSE streaming, conversation history",
    "static/js/signal.js": "Signal page — decoder terminal input, tx hash lookup, solver leaderboard",
    "static/js/arrival.js": "Onboarding — captain creation, mining tutorial, crew page intro",
    "static/js/inventory.js": "Inventory page — discoveries, equipment, wallet, transaction history tabs",
    "static/js/pilgrimbot.js": "PilgrimBot chat — sidebar, message rendering, role picker, bug creation, markdown rendering",
    "static/js/discovery-modal.js": "Discovery detail modal — stats, extraction dialog, keep/extract choice",
    "static/js/discovery_utils.js": "Discovery helpers — rarity colors, category icons, value formatting",
    "static/js/admin-bugs.js": "Bug tracker admin — bug list, detail modal, status changes, comments, screenshots",
    "static/js/brainstorm-chat.js": "Brainstorm AI chat — Claude-powered discussion per brainstorm page",
    "static/js/brainstorm-comments.js": "Brainstorm comments — threaded discussion, add/edit/delete per section",
    # CSS files
    "static/css/core.css": "Shared styles — layout, 5-tab nav, modals, toast, buttons, Mars theme, colorblind-safe palette, status bar",
    "static/css/colony.css": "Colony page styles — discovery cards, equipment grid, activity feed, tabs",
    "static/css/crew.css": "Crew page styles — captain card, stats display, trail missions, SV ticker",
    "static/css/depot.css": "Depot page styles — shop cards, upgrade tiers, infrastructure build UI",
    "static/css/signal.css": "Signal page styles — decoder terminal, solver list, origin site cards",
    "static/css/pilgrimbot.css": "PilgrimBot styles — chat layout, sidebar, messages, role picker",
    # HTML templates
    "templates/base.html": "Base template — 5-tab nav, status bar, ARIA widget, balance display, Mars theme",
    # Config files
    "config.py": "Central config — UI_ICONS, scientists, stat generation, infrastructure defs, port management",
    "config_upgrades.py": "Upgrade catalog — 11 categories × 10 levels (vehicles, power_core, mining_drone, scanners, storage, etc.)",
    "config_infrastructure.py": "Infrastructure catalog — 13 buildings × 10 levels (solar, battery, habitat, xeno lab, nuclear, etc.)",
    "config_tech.py": "Tech tree config — 4 branches × 5 techs, SV costs, research times, branch effects",
    "config_shop.py": "Shop catalog — one-time depot items, trail duration calc, build time formula",
    # Utilities without good docstrings
    "utilities/gmail_utils.py": "SHIM — real transport in utilities/email/transport.py. Email sending via Gmail API",
    "utilities/email/transport.py": "Gmail API transport, HTML message assembly, send to recipient",
    "utilities/email/fomo.py": "FOMO email context + send_welcome_back_email, generate_fomo_email_data, calculate_days_away",
    "utilities/email/actions.py": "generate_action_url for email CTA links (claim discoveries, claim sepolia)",
    "utilities/email/bonds.py": "ARIA bond email composition",
    "utilities/email/admin.py": "admin-targeted notifications",
    "utilities/email/mentions.py": "@-mention notifications",
    "utilities/fomo_email_utils.py": "SHIM — real code in utilities/email/fomo.py + utilities/postgres/users + utilities/video_utils",
    "utilities/video_utils.py": "MP4→GIF conversion, extract_thumbnail, get_user_video_data for FOMO emails",
    "utilities/replicate_utils.py": "All Replicate-backed generation + analysis — Flux image edits, Kontext progressive edits, Nano Banana Pro, Wan video, LLaVA vision. FluxGenerator + VisionAnalyzer classes.",
    "utilities/mars_math.py": "Mars math — haversine_distance(), Mars radius constant, coordinate calculations",
    "utilities/session_helpers.py": "Session cache invalidation — invalidate_balance_cache, invalidate_nav_cache, clear helpers",
    # Key docs
    "CLAUDE.md": "Developer guide — code philosophy, critical rules, frontend patterns, deployment, ARIA context",
    "docs/architecture.md": "Architecture reference — file responsibilities, utility table, template/CSS/JS structure",
    "docs/patterns.md": "Code patterns — db_cursor usage, session cache keys, display currency, API routes, upgrade system",
    "docs/PILGRIMS.md": "Design bible — story, game philosophy, core loop, visual style guide, easter eggs, lore",
}

# Extra keywords for key files (terms users search for but aren't in docstrings)
EXTRA_KEYWORDS = {
    "utilities/infrastructure_utils.py": "SHIM — real code in utilities/infrastructure/ package. effective rate, mining drone, base total, income breakdown",
    "utilities/infrastructure/income.py": "calculate_accumulated_income, scientist shard multiplier, battery night multiplier, maintenance drone, shard generation rate, passive income, dust storm",
    "utilities/infrastructure/environment.py": "MARS_SOL_HOURS, ACCUMULATION_CAP_HOURS, day-night cycle, dust factor, temperature factor, latitude factor",
    "utilities/infrastructure/construction.py": "start_construction, build requirements, welcome bonus, check_construction_status",
    "utilities/infrastructure/views.py": "get_infrastructure_page_data, build handler, infrastructure status",
    "utilities/infrastructure/effects.py": "get_user_infrastructure_effects, infrastructure multipliers aggregation",
    "utilities/upgrades_utils.py": "upgrade cost, level, tier, build time, upgrade effects, passive income multiplier, power core",
    "utilities/page_data_utils.py": "SHIM — real code in utilities/views/ package. dashboard data, colony page, fleet status",
    "utilities/views/dashboard.py": "dashboard data, mission control, income display, effective rate",
    "utilities/views/colony.py": "colony page data, discoveries, equipment, fog radius, activity feed",
    "utilities/views/arrival.py": "arrival page, onboarding flow, new captain intro",
    "utilities/views/while_you_were_away.py": "while-you-were-away greeting, offline summary, idle discoveries",
    "utilities/views/depot.py": "depot page data, shop state, fog-of-war",
    "utilities/views/misc.py": "misc page data helpers",
    "config_upgrades.py": "upgrade catalog, item config, level stats, cost multiplier, rover, shuttle, scanner, storage, power core, mining drone",
    "config_infrastructure.py": "building catalog, solar array, battery, habitat, xenobiology lab, nuclear plant, fusion reactor, greenhouse, build time, generation rate",
    "config_shop.py": "shop items, depot, purchase, buy, drone, equipment, one-time items, shop catalog",
    "config_tech.py": "tech tree, research branches, SV cost, research time, branch effects, exploration engineering xenobiology signal",
    "utilities/expedition_utils.py": "SHIM — real code in utilities/expeditions/ package. expedition speed, vehicle, travel time, trail, cost",
    "utilities/expeditions/config.py": "BASE_SPEED_KM_PER_HOUR, BASE_COST_PER_KM, LIFE_SUPPORT_PER_DAY, EVA_HOURS_PER_DAY, TERRAIN_MODIFIERS",
    "utilities/expeditions/cost.py": "calculate_expedition_cost, generate_expedition_narrative, sort_landmarks_by_cost",
    "utilities/expeditions/preview.py": "get_expedition_cost_preview, get_expedition_cost_preview_formatted, charisma/logistics/experience discounts",
    "utilities/expeditions/lifecycle.py": "launch_expedition, complete_expedition_if_ready, recall_expedition, fog_radius calculation, shard/SV reward",
    "utilities/expeditions/travel.py": "calculate_segmented_travel_time, trail speed bonus, segment travel",
    "utilities/expeditions/terrain.py": "calculate_speed_multiplier, calculate_travel_time, terrain info, geographic validity",
    "utilities/expeditions/trails.py": "handle_trail_build_request, EVA suit trail bonus, consumables",
    "utilities/expeditions/haul_data.py": "build_expedition_haul, discovery payload",
    "utilities/expeditions/formatters.py": "expedition history payload, items payload",
    "utilities/expeditions/page_data.py": "get_expeditions_page_data",
    "utilities/aria_utils.py": "ARIA chat, colony snapshot, AI assistant, personality tier, relationship",
    "utilities/shop_utils.py": "depot, shop items, purchase, mining drone, power equipment, availability",
    "utilities/discovery_utils.py": "discovery analysis, extraction, rarity, progressive weights, shard payout",
    "utilities/signal_utils.py": "SHIM — real code in utilities/signal/ package. signal decoder, origin sites, echo, ARG",
    "utilities/signal/claims.py": "claim_origin_site, visit_origin_site, decode_lost_signal_site, decode_signal_puzzle, decode_signal_tx, puzzle solvers",
    "utilities/signal/sites.py": "origin sites CRUD, echo sites, network reconstruction percent (origin_progress + echo_progress), closest pilgrim",
    "utilities/signal/handlers.py": "handle_origin_site_claim, handle_origin_site_visit, commander name lookup",
    "utilities/signal/rewards.py": "legendary item generation for origin sites, visitor rewards, eligibility payload",
    "utilities/signal/config.py": "visitor tiers, signal config",
    "utilities/db_bugs.py": "bug tracker, bugs, QA, priority, status, comments, history, screenshot, complete, reopen",
    "utilities/db_brainstorm.py": "brainstorm, comments, discussion, design decisions, team notes",
    "utilities/pilgrimbot_utils.py": "SHIM — real code in utilities/pilgrimbot/ package. pilgrimbot entry, chat",
    "utilities/pilgrimbot/personas.py": "PilgrimBot role personas and system prompts",
    "utilities/pilgrimbot/storage.py": "conversation persistence, chat history",
    "utilities/pilgrimbot/file_reader.py": "codebase file reader tool",
    "utilities/pilgrimbot/tool_loop.py": "Anthropic tool-use loop, bug queries, player data lookups",
    "utilities/pilgrimbot/context.py": "codemap loader, math_registry loader, system context builder",
    "utilities/pilgrimbot/streaming.py": "SSE streaming response handler",
    "utilities/pilgrimbot_data.py": "player data queries, balance, upgrades, expeditions, research, crew, leaderboard, colony state",
    "utilities/db_map.py": "map, landmarks, discoveries, fog of war, frontier, exploration, coordinates",
    "utilities/crew_utils.py": "crew, captain, scientist, trails, missions, recovery",
    "utilities/research_utils.py": "research, tech tree, science value, SV, lab, branches",
    "utilities/tech_utils.py": "tech research, start research, complete research, SV balance, tech effects",
    "utilities/mars_environment_utils.py": "mars conditions, sol cycle, solar efficiency, dust storm, atmospheric, fee multiplier",
    "utilities/idle_discovery_utils.py": "passive discovery, idle generation, background discoveries",
    "utilities/session_helpers.py": "session cache, invalidate balance, invalidate nav, cache keys",
    "utilities/db_users.py": "SHIM — real code in utilities/postgres/users.py",
    "utilities/postgres/users.py": "user CRUD, auth, session hydration, get_user_by_id, get_user_by_email, get_all_users, calculate_reroll_cost, calculate_transmutation_cost",
    "utilities/postgres/trails/segments.py": "trail km add, SV per km (2 SV/km), cron_drone_trail_build passive trail",
    "utilities/postgres/trails/crew.py": "crew mission XP (5 per mission), captain/scientist/aria XP tracking",
    "utilities/postgres/trails/aria_skills.py": "use_aria_resonance, resonance cooldown 24h, ARIA skill XP",
    "utilities/db_expeditions.py": "expedition CRUD, discovery items, expedition status",
    "utilities/db_wallets.py": "wallet operations, sepolia balance, primary wallet",
    "utilities/depot_utils.py": "balance helpers, wallet info, pricing, purchases, eth_to_display, display_to_eth",
    "static/js/core.js": "shared utilities, modal, toast, formatCountdown, tab switching, balance display, nav prefetch",
    "static/js/dashboard.js": "income display, effective rate UI, mining drone bonus display, base total display, harvest",
    "static/js/expeditions.js": "mars map, leaflet, landmarks, expedition launch, fog of war, vehicle select",
    "static/js/colony.js": "discovery grid, equipment list, activity feed, asset management",
    "static/js/depot.js": "shop purchase, upgrade UI, infrastructure building, commander services",
    "static/js/crew.js": "captain stats, image management, SV ticker, reroll, transmute",
    "static/js/aria.js": "ARIA orb, chat widget, streaming, conversation",
    "docs/PILGRIMS.md": "design bible, game philosophy, story, lore, mars colony, core loop, easter eggs, visual style",
    "docs/architecture.md": "file structure, utilities, templates, CSS, JS, routes, architecture",
    "docs/patterns.md": "database access, session cache, display currency, API patterns, db_cursor",
}

# Skip these directories
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing"}

# Skip deprecated/blocked files (matches deploy.py blocklist)
# andy_check.py: deploy-time dev smoke test, NOT gameplay — must never appear
# in codemap.json so PilgrimBot / ARIA don't surface it to captains.
SKIP_FILES = {"gcloud_deploy.py", "git_push.sh", "andy_check.py"}


def extract_python_summary(filepath):
    """Extract module docstring + public function signatures from a .py file.

    If the file is a back-compat shim (docstring mentions "Back-compat shim"),
    also record the real source modules it re-exports from so PilgrimBot can
    direct readers to the real home instead of the shim.
    """
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception:
        return None

    info = {}
    docstring = ast.get_docstring(tree)
    if docstring:
        info["description"] = docstring.strip().split("\n")[0]

    is_shim = bool(docstring) and (
        "Back-compat shim" in docstring
        or docstring.startswith("Shim ")
        or docstring.startswith("Shim —")
        or docstring.startswith("Shim for")
    )

    funcs = []
    shim_of = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            doc = ast.get_docstring(node)
            entry = node.name
            if doc:
                entry += f" — {doc.strip().split(chr(10))[0]}"
            funcs.append(entry)
        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node)
            entry = f"class {node.name}"
            if doc:
                entry += f" — {doc.strip().split(chr(10))[0]}"
            funcs.append(entry)
        elif is_shim and isinstance(node, ast.ImportFrom) and node.module:
            # Record real source modules this shim re-exports from
            shim_of.add(node.module)

    if funcs:
        info["exports"] = funcs
    if is_shim:
        info["shim"] = True
        if shim_of:
            info["shim_of"] = sorted(shim_of)

    return info if info else None


def extract_js_summary(filepath):
    """Extract description from header comment + top-level function names from a .js file."""
    try:
        with open(filepath) as f:
            source = f.read()
    except Exception:
        return None

    info = {}

    # Extract description from header comment (first /* */ or // block)
    header_match = re.match(r'\s*/\*\*?\s*(.*?)\s*\*/', source, re.DOTALL)
    if header_match:
        desc = header_match.group(1).strip().split('\n')[0].strip(' *')
        if desc:
            info["description"] = desc
    else:
        # Try // comment block at top — skip separator lines (===, ---)
        lines = source.split('\n')[:8]
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('//'):
                text = stripped.lstrip('/ =-').strip()
                if text and len(text) > 5 and not text.startswith('{') and not re.match(r'^[=\-*]+$', text):
                    info["description"] = text
                    break

    funcs = []
    for match in re.finditer(
        r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:function|\())', source
    ):
        name = match.group(1) or match.group(2)
        if name and not name.startswith("_"):
            funcs.append(name)
    if funcs:
        info["exports"] = funcs

    return info if info else None


def extract_html_summary(filepath):
    """Extract template purpose from filename and key content patterns."""
    try:
        with open(filepath) as f:
            source = f.read()
    except Exception:
        return None

    info = {}
    # Check for block title
    title_match = re.search(r'{%\s*block\s+title\s*%}(.*?){%', source)
    if title_match:
        info["description"] = f"Page: {title_match.group(1).strip()}"

    # Check for key data patterns
    patterns = []
    if "PAGE_DATA" in source or "pageData" in source or 'type="application/json"' in source:
        patterns.append("has PAGE_DATA bridge")
    if "switchTab" in source or "tab-btn" in source:
        patterns.append("tabbed interface")
    if "api/" in source:
        api_calls = re.findall(r'["\']/(api/\w+/?\w*)["\']', source)
        if api_calls:
            patterns.append(f"calls: {', '.join(set(api_calls[:5]))}")
    if patterns:
        info["notes"] = patterns

    return info if info else None


def extract_css_summary(filepath):
    """Extract description from header comment, fallback to filename."""
    try:
        with open(filepath) as f:
            source = f.read()
    except Exception:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        return {"description": f"Styles for {basename}"}

    # Try /* */ comment at top
    header_match = re.match(r'\s*/\*\s*(.*?)\s*\*/', source, re.DOTALL)
    if header_match:
        desc = header_match.group(1).strip().split('\n')[0].strip(' *=-')
        if desc and len(desc) > 5:
            return {"description": desc}

    basename = os.path.splitext(os.path.basename(filepath))[0]
    return {"description": f"Styles for {basename}"}


def extract_md_summary(filepath):
    """Extract heading structure from a Markdown file."""
    try:
        with open(filepath) as f:
            source = f.read()
    except Exception:
        return None

    info = {}
    # First H1 heading
    h1 = re.search(r'^#\s+(.+)', source, re.MULTILINE)
    if h1:
        info["description"] = h1.group(1).strip()

    # H2 sections as "exports"
    sections = re.findall(r'^##\s+(.+)', source, re.MULTILINE)
    if sections:
        info["exports"] = [s.strip() for s in sections[:12]]

    return info if info else None


def generate_codemap():
    """Walk the codebase and generate the codemap."""
    codemap = {}

    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skip excluded dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in sorted(filenames):
            if fname in SKIP_FILES:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in CODE_EXTS:
                continue

            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(full_path, ROOT)

            # Skip archive paths
            if "archive/" in rel_path:
                continue

            if ext == ".py":
                summary = extract_python_summary(full_path)
            elif ext == ".js":
                summary = extract_js_summary(full_path)
            elif ext == ".html":
                summary = extract_html_summary(full_path)
            elif ext == ".css":
                summary = extract_css_summary(full_path)
            elif ext == ".md":
                summary = extract_md_summary(full_path)
            else:
                summary = None

            if summary:
                # Cap exports to keep file compact
                if "exports" in summary and len(summary["exports"]) > 15:
                    summary["exports"] = summary["exports"][:15]
                # Apply manual description if auto-extracted is missing or too short
                if rel_path in MANUAL_DESCRIPTIONS:
                    auto_desc = summary.get("description", "")
                    if not auto_desc or len(auto_desc) < 20:
                        summary["description"] = MANUAL_DESCRIPTIONS[rel_path]
                # Add extra search keywords for key files
                if rel_path in EXTRA_KEYWORDS:
                    summary["keywords"] = EXTRA_KEYWORDS[rel_path]
                codemap[rel_path] = summary

    return codemap


def main():
    codemap = generate_codemap()
    with open(OUTPUT, "w") as f:
        json.dump(codemap, f, indent=2, ensure_ascii=False)

    print(f"Codemap: {len(codemap)} files indexed → {OUTPUT}")
    # Show size
    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"Size: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
