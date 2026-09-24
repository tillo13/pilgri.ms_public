#!/usr/bin/env python3
"""
PilgrimBot Smoke Test — validates the codebase Q&A bot end-to-end.

Tests the full pipeline: codemap → file finding → local code reading → Claude answers.
Reads code directly from the local codebase (same as production on GCP).

Usage:
    python tools/smoke_test_pilgrimbot.py              # Run all tests
    python tools/smoke_test_pilgrimbot.py --quick      # Skip Claude Q&A (free)
    python tools/smoke_test_pilgrimbot.py --verbose     # Show full answers
"""

import json
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = []
FAILED = []
SKIPPED = []


def test(name):
    """Simple test decorator — prints pass/fail, tracks results."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if result is None or result is True:
                    PASSED.append(name)
                    print(f"  ✅ {name}")
                    return True
                else:
                    FAILED.append((name, str(result)))
                    print(f"  ❌ {name}: {result}")
                    return False
            except Exception as e:
                FAILED.append((name, str(e)))
                print(f"  ❌ {name}: {e}")
                return False
        return wrapper
    return decorator


# =============================================================================
# TIER 1: Codemap & file-finding logic (no network, no API cost)
# =============================================================================

@test("codemap loads from local file")
def test_codemap_local():
    """codemap.json should exist locally (generated on deploy)."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codemap.json")
    if not os.path.exists(path):
        return "codemap.json not found — run: python -m tools.generate_codemap"
    with open(path) as f:
        data = json.load(f)
    assert len(data) > 10, f"codemap too small: {len(data)} files"
    # Spot-check key files are indexed
    for key_file in ["app.py", "config.py", "utilities/infrastructure_utils.py"]:
        assert key_file in data, f"{key_file} missing from codemap"


@test("find_relevant_files matches infrastructure questions")
def test_file_finding_infrastructure():
    from utilities.pilgrimbot_utils import find_relevant_files
    files = find_relevant_files("How is the effective rate calculated?")
    assert len(files) > 0, "No files found"
    paths_str = " ".join(files)
    assert "infrastructure" in paths_str or "upgrade" in paths_str, (
        f"Expected infrastructure/upgrade file, got: {files}")


@test("find_relevant_files matches expedition questions")
def test_file_finding_expeditions():
    from utilities.pilgrimbot_utils import find_relevant_files
    files = find_relevant_files("How fast do expeditions travel?")
    assert len(files) > 0, "No files found"
    paths_str = " ".join(files)
    assert "expedition" in paths_str, f"Expected expedition file, got: {files}"


@test("find_relevant_files matches tech tree questions")
def test_file_finding_tech():
    from utilities.pilgrimbot_utils import find_relevant_files
    files = find_relevant_files("What does research cost at higher levels?")
    assert len(files) > 0, "No files found"
    paths_str = " ".join(files)
    assert "tech" in paths_str, f"Expected tech file, got: {files}"


@test("find_relevant_files matches depot/shop questions")
def test_file_finding_depot():
    from utilities.pilgrimbot_utils import find_relevant_files
    files = find_relevant_files("What items can I buy in the depot?")
    assert len(files) > 0, "No files found"
    paths_str = " ".join(files)
    assert "upgrade" in paths_str or "shop" in paths_str or "depot" in paths_str, (
        f"Expected shop/upgrade/depot file, got: {files}")


@test("_find_best_section extracts relevant function")
def test_best_section():
    from utilities.pilgrimbot_utils import _find_best_section
    fake_code = """
def calculate_income(user_id):
    base = get_base_rate(user_id)
    return base * multiplier

def unrelated_function():
    pass

def calculate_effective_rate(user_id):
    income = calculate_income(user_id)
    drone_bonus = get_mining_drone_bonus(user_id)
    effective = income + drone_bonus
    return effective
"""
    pos = _find_best_section(fake_code, ["effective", "rate", "mining", "drone"])
    assert pos is not None, "Should find a matching section"
    section = fake_code[pos:pos + 200]
    assert "effective_rate" in section, f"Found wrong section: {section[:80]}"


@test("generate_title truncates long messages")
def test_generate_title():
    from utilities.pilgrimbot_utils import generate_title
    short = generate_title("How do shards work?")
    assert short == "How do shards work?", f"Short title wrong: {short}"
    long_msg = "A" * 100
    title = generate_title(long_msg)
    assert len(title) <= 83, f"Title too long: {len(title)}"  # 80 + "..."


@test("SYSTEM_PROMPT forbids code terms")
def test_system_prompt():
    from utilities.pilgrimbot_utils import SYSTEM_PROMPT
    assert "NEVER use programming terms" in SYSTEM_PROMPT
    assert "function" in SYSTEM_PROMPT  # listed as forbidden term
    assert "math" in SYSTEM_PROMPT.lower()  # math is encouraged


# =============================================================================
# TIER 2: Local file reading (no network, no API cost)
# =============================================================================

@test("read_local_file reads infrastructure_utils.py")
def test_read_local_infrastructure():
    from utilities.pilgrimbot_utils import read_local_file
    content = read_local_file("utilities/infrastructure_utils.py")
    assert content is not None, "Could not read infrastructure_utils.py"
    assert "income" in content.lower() or "rate" in content.lower(), (
        "infrastructure_utils.py doesn't contain expected content")


@test("read_local_file reads app.py")
def test_read_local_app():
    from utilities.pilgrimbot_utils import read_local_file
    content = read_local_file("app.py")
    assert content is not None, "Could not read app.py"
    assert "flask" in content.lower(), "app.py doesn't look like Flask"


@test("read_local_file blocks non-code files")
def test_read_local_blocks_secrets():
    from utilities.pilgrimbot_utils import read_local_file
    # Should refuse to read .json, .md, .env, etc.
    assert read_local_file("codemap.json") is None, "Should block .json"
    assert read_local_file("CLAUDE.md") is None, "Should block .md"
    assert read_local_file("deploy.json") is None, "Should block deploy.json"


@test("read_local_file blocks sensitive directories")
def test_read_local_blocks_dirs():
    from utilities.pilgrimbot_utils import read_local_file
    assert read_local_file(".claude/settings.json") is None, "Should block .claude/"
    assert read_local_file("tools/credentials/key.py") is None, "Should block credentials/"


@test("read_local_file smart section extraction")
def test_read_local_smart_section():
    from utilities.pilgrimbot_utils import read_local_file
    content = read_local_file(
        "utilities/infrastructure_utils.py",
        max_chars=3000,
        search_terms=["effective", "rate", "mining", "drone"]
    )
    assert content is not None, "Could not read infrastructure_utils.py"
    content_lower = content.lower()
    assert "effective" in content_lower or "rate" in content_lower or "income" in content_lower, (
        "Smart extraction didn't find effective rate section")


@test("full pipeline: question → files → code context")
def test_full_pipeline():
    """End-to-end: question finds files, files produce code context."""
    from utilities.pilgrimbot_utils import find_relevant_files, read_local_file, load_codemap
    q = "Why does the Mining Drone come after the Base Total?"
    relevant = find_relevant_files(q)
    assert len(relevant) > 0, "No files found"
    codemap = load_codemap()
    code_context = ""
    for fpath in relevant:
        content = read_local_file(fpath, search_terms=["mining", "drone", "base", "total"])
        if content:
            code_context += content
    assert len(code_context) > 100, (
        f"Code context too small ({len(code_context)} chars) — pipeline broken")


# =============================================================================
# TIER 3: Claude Q&A tests (costs API credits, tests actual answers)
# =============================================================================

# Luke's REAL questions — sourced from Google Sheet bug tracker, Discord,
# and playtesting sessions. Luke is smart, understands math, NOT a coder.
#
# Question categories (from 500+ bugs Luke filed):
#   1. "Where does X show up?" — can't trace where bonuses apply
#   2. "Is this correct?" — data accuracy doubts
#   3. "What does X actually do?" — unclear item/upgrade effects
#   4. "Why doesn't X match?" — math doesn't add up on screen
#   5. "How do I see/find X?" — missing info in UI
#   6. "Is this a bug or works as designed?" — unclear behavior
#
# Each test validates:
#   expect_any:  at least one keyword MUST appear (on-topic)
#   reject_any:  code-speak that must NEVER appear (plain-English)
#   min_length:  minimum answer length (no cop-outs)
#
QA_PAIRS = [
    # --- ECONOMY: Luke's #1 confusion area ---
    {
        # Luke's exact words from Discord + screenshot
        "question": "Why does the Mining Drone come in after the Base Total and not before? I tried doing the math on a calculator and it never matches the Effective Rate shown on screen.",
        "expect_any": ["flat", "added", "after", "multiplied", "base total"],
        "reject_any": ["function", "def ", "variable", "parameter", ".py"],
        "description": "Mining Drone ordering (Luke's exact question)",
        "min_length": 100,
    },
    {
        # Luke literally said "have yet to figure it out" after months
        "question": "How is the Effective Rate calculated? I see Base Total, then High-Efficiency Panels as a multiplier, Tech Bonus as a multiplier, then Mining Drone as a flat add. Can you show me the actual formula with example numbers?",
        "expect_any": ["base total", "×", "multiplier", "+"],
        "reject_any": ["function", "def ", "variable", "parameter", ".py", "returns"],
        "description": "Effective Rate formula with real math",
        "min_length": 150,
    },
    {
        "question": "What's the difference between the Ore Processing Refinery rate and the Solar Array rate? Why does solar show a percentage next to it?",
        "expect_any": ["solar", "day", "night", "refinery", "24"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Solar vs Refinery generation",
        "min_length": 100,
    },
    # --- "WHERE DOES X SHOW UP?" (Luke's pattern #1) ---
    {
        # From completed bug: "20% Passive income from Tech — Where does this bonus come into play?"
        "question": "I completed a tech that says it gives 20% passive income bonus. Where does that actually show up? I don't see it anywhere on my dashboard.",
        "expect_any": ["passive income", "multiplier", "tech", "generation"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Where does tech passive income bonus show?",
        "min_length": 80,
    },
    # --- "WHAT DOES X ACTUALLY DO?" (Luke's pattern #3) ---
    {
        # From active bug: "What is Ops Fee"
        "question": "There is an 'Ops Fee' on some of the more expensive depot buildings. What is that and why do some items have it but not others?",
        "expect_any": ["fee", "cost", "shard", "purchase"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "What is Ops Fee?",
        "min_length": 80,
    },
    {
        # From active bug: "Habitat Module gives you expedition slots up to 7? but you only have 3 max vehicles?"
        "question": "The Habitat Module says it gives me more expedition slots, but I only have 3 vehicles. What's the point of having 7 expedition slots if I can only use 3?",
        "expect_any": ["expedition", "slot", "vehicle", "concurrent"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Habitat Module expedition slots vs vehicles",
        "min_length": 80,
    },
    # --- "IS THIS CORRECT?" (Luke's pattern #2) ---
    {
        # From active bug: "vehicle capacity incorrect? — came back with 98 items"
        "question": "I just came back from an expedition with my drone and it brought back 98 items. That seems like way too many. Is the vehicle capacity working right?",
        "expect_any": ["cargo", "capacity", "item", "weight", "physical"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Vehicle cargo capacity (98 items bug)",
        "min_length": 80,
    },
    # --- EXPEDITIONS ---
    {
        # From completed bug: "Details on how fast a vehicle can go — just says 5.5x faster, but faster than what?"
        "question": "My vehicle says it's 5.5x faster but faster than what? What's the base speed? I want to know actual travel times, not just multipliers.",
        "expect_any": ["speed", "base", "km", "hour", "time"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Vehicle speed — 5.5x faster than what?",
        "min_length": 80,
    },
    # --- UPGRADES / DEPOT ---
    {
        # From active bug: "Standardize Upgrade Increases — 1.2x vs 20%"
        "question": "Some upgrades show bonuses as '1.2x' and others show '20%'. Are those the same thing? It's confusing when different pages show it differently.",
        "expect_any": ["1.2", "20%", "same", "multiplier", "display"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "1.2x vs 20% display inconsistency",
        "min_length": 80,
    },
    {
        "question": "How much more expensive does each upgrade level get? Is there a pattern or does it jump randomly?",
        "expect_any": ["1.12", "multiplier", "level", "cost", "more expensive"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Upgrade cost scaling (1.12x pattern)",
        "min_length": 80,
    },
    # --- "IS THIS A BUG OR WORKS AS DESIGNED?" (Luke's pattern #6) ---
    {
        # From completed bug: "Long expeditions should bring back more/better discoveries"
        "question": "I sent a 2000km expedition and got basically the same stuff as a 200km trip. Is that intentional? Feels like long trips should bring back better stuff.",
        "expect_any": ["distance", "reward", "rarity", "multiplier", "longer"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Long expedition reward scaling",
        "min_length": 80,
    },
    # --- ARIA ---
    {
        # From completed bug: "ARIA doesn't know what Regolith Forge is"
        "question": "I asked ARIA about the Regolith Forge and she had no idea what it was. Does ARIA know about all my buildings and upgrades?",
        "expect_any": ["colony", "building", "upgrade", "know", "snapshot"],
        "reject_any": ["function", "def ", "variable", ".py", "load_colony_snapshot"],
        "description": "ARIA knowledge of specific buildings",
        "min_length": 80,
    },
    # --- BUILD TIMES ---
    {
        # From active bug: "Way to speed up Depot build times"
        "question": "Is there any way to speed up build times? Some of these upgrades take days and there's nothing I can do but wait.",
        "expect_any": ["build", "time", "day", "speed", "wait"],
        "reject_any": ["function", "def ", "variable", ".py"],
        "description": "Can you speed up build times?",
        "min_length": 80,
    },
]


def run_qa_test(qa, verbose=False):
    """Ask PilgrimBot a question via Claude and validate the answer."""
    from utilities.pilgrimbot_utils import (
        find_relevant_files, read_local_file, load_codemap, SYSTEM_PROMPT
    )
    from utilities.claude_utils import create_client, CLAUDE_MODELS

    model = CLAUDE_MODELS.get("haiku-4.5", "claude-haiku-4-5-20251001")

    # Step 1: Find relevant files (same as production pipeline)
    relevant = find_relevant_files(qa["question"])

    # Step 2: Read code context from local files
    codemap = load_codemap()
    code_context = ""
    msg_stopwords = {"have", "been", "this", "that", "with", "from", "what", "does",
                     "will", "would", "could", "about", "there", "also", "just", "some",
                     "into", "over", "after", "before", "many", "like", "know"}
    search_terms = [w.lower().strip("?.,!()\"'") for w in qa["question"].split()
                    if len(w) > 3 and w.lower().strip("?.,!()\"'") not in msg_stopwords]

    for fpath in relevant:
        extra_terms = search_terms[:]
        if fpath in codemap and "exports" in codemap[fpath]:
            for export in codemap[fpath]["exports"]:
                fname = export.split(" —")[0].split(" ")[0].replace("class ", "")
                extra_terms.append(fname.lower())
        content = read_local_file(fpath, search_terms=extra_terms)
        if content:
            code_context += f"\n--- {fpath} ---\n{content}\n"

    if not code_context:
        return f"No code context found for: {qa['question']}"

    # Step 3: Ask Claude
    system = SYSTEM_PROMPT + f"\n\nRELEVANT CODE CONTEXT:\n{code_context}"
    messages = [{"role": "user", "content": qa["question"]}]

    client = create_client(model=model)
    answer = client.chat(messages, system=system, max_tokens=800, temperature=0.3)

    if verbose:
        print(f"\n    📝 Q: {qa['question']}")
        print(f"    📄 Files: {relevant}")
        print(f"    💬 A: {answer[:300]}...")

    # Step 4: Validate answer quality
    answer_lower = answer.lower()

    # Must contain at least one expected keyword
    found_expected = [kw for kw in qa["expect_any"] if kw in answer_lower]
    if not found_expected:
        return (f"Answer missing expected keywords. "
                f"Wanted any of {qa['expect_any']}, answer: {answer[:150]}...")

    # Must NOT contain code-speak (strict terms only — avoid false positives
    # on natural English like "variable weather" or "returns to base")
    CODE_ONLY_TERMS = {"def ", ".py", "parameter"}  # always code if present
    found_rejected = []
    for kw in qa["reject_any"]:
        if kw not in answer_lower:
            continue
        if kw in CODE_ONLY_TERMS:
            found_rejected.append(kw)
        elif kw == "function" and "function" in answer_lower and "functionality" not in answer_lower:
            found_rejected.append(kw)
        elif kw == "variable" and "variable" in answer_lower:
            # Allow "variable" in natural context (weather, rate, etc.)
            # Only flag if it appears near code-like context
            if any(p in answer_lower for p in ["variable name", "set the variable", "this variable"]):
                found_rejected.append(kw)
        elif kw == "returns" and "returns" in answer_lower:
            # Allow "returns to base", "returns a reward"
            if any(p in answer_lower for p in ["returns the", "returns a value", "returns true"]):
                found_rejected.append(kw)
        elif kw not in {"function", "variable", "returns"}:
            found_rejected.append(kw)
    if found_rejected:
        return (f"Answer contains code terms: {found_rejected}. "
                f"PilgrimBot should speak plain English, not code.")

    # Answer shouldn't be too short (sign of failure or cop-out)
    min_len = qa.get("min_length", 50)
    if len(answer) < min_len:
        return f"Answer too short ({len(answer)} chars, need {min_len}): {answer[:100]}..."

    return True


# =============================================================================
# RUNNER
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="PilgrimBot Smoke Test")
    parser.add_argument("--quick", action="store_true",
                        help="Skip Claude Q&A tests (no API cost)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full answers from Claude")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"🤖 PILGRIMBOT SMOKE TEST")
    print(f"{'=' * 60}\n")

    # Tier 1: Codemap & file-finding logic
    print("── Tier 1: Codemap & file finding ──")
    test_codemap_local()
    test_file_finding_infrastructure()
    test_file_finding_expeditions()
    test_file_finding_tech()
    test_file_finding_depot()
    test_best_section()
    test_generate_title()
    test_system_prompt()

    # Tier 2: Local file reading
    print("\n── Tier 2: Local file reading ──")
    test_read_local_infrastructure()
    test_read_local_app()
    test_read_local_blocks_secrets()
    test_read_local_blocks_dirs()
    test_read_local_smart_section()
    test_full_pipeline()

    # Tier 3: Claude Q&A (skip with --quick)
    if args.quick:
        print("\n── Tier 3: Claude Q&A (skipped — --quick) ──")
        SKIPPED.append("Claude Q&A tests (--quick flag)")
    else:
        print("\n── Tier 3: Claude Q&A ──")
        for qa in QA_PAIRS:
            name = f"Q&A: {qa['description']}"
            try:
                result = run_qa_test(qa, verbose=args.verbose)
                if result is True:
                    PASSED.append(name)
                    print(f"  ✅ {name}")
                else:
                    FAILED.append((name, str(result)))
                    print(f"  ❌ {name}: {result}")
            except Exception as e:
                FAILED.append((name, str(e)))
                print(f"  ❌ {name}: {e}")

    # Results
    print(f"\n{'=' * 60}")
    print(f"📊 RESULTS")
    print(f"{'=' * 60}")
    print(f"  ✅ Passed:  {len(PASSED)}")
    print(f"  ❌ Failed:  {len(FAILED)}")
    print(f"  ⏭️  Skipped: {len(SKIPPED)}")

    if FAILED:
        print(f"\n❌ FAILURES:")
        for name, error in FAILED:
            print(f"   • {name}")
            if args.verbose:
                print(f"     {error}")

    if SKIPPED and args.verbose:
        print(f"\n⏭️  SKIPPED:")
        for name in SKIPPED:
            print(f"   • {name}")

    print(f"\n{'=' * 60}")
    if FAILED:
        print("🔴 PILGRIMBOT TESTS FAILED")
        return 1
    print("🟢 ALL PILGRIMBOT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
