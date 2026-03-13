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
CODE_EXTS = {".py", ".js", ".css", ".html"}

# Extra keywords for key files (terms users search for but aren't in docstrings)
EXTRA_KEYWORDS = {
    "utilities/infrastructure_utils.py": "effective rate, mining drone, base total, income breakdown, shard generation rate, passive income, multiplier, bonus",
    "utilities/upgrades_utils.py": "upgrade cost, level, tier, build time, upgrade effects, passive income multiplier",
    "utilities/page_data_utils.py": "dashboard data, colony page, fleet status, activity feed",
    "config_upgrades.py": "upgrade catalog, item config, level stats, cost multiplier",
    "utilities/expedition_utils.py": "expedition speed, vehicle, travel time, trail",
    "utilities/aria_utils.py": "ARIA chat, colony snapshot, AI assistant",
    "utilities/shop_utils.py": "depot, shop items, purchase, mining drone, power equipment",
    "static/js/dashboard.js": "income display, effective rate UI, mining drone bonus display, base total display",
}

# Skip these directories
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing"}

# Skip deprecated/blocked files (matches deploy.py blocklist)
SKIP_FILES = {"gcloud_deploy.py", "config_shop.py", "git_push.sh"}


def extract_python_summary(filepath):
    """Extract module docstring + public function signatures from a .py file."""
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

    funcs = []
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
    if funcs:
        info["exports"] = funcs

    return info if info else None


def extract_js_summary(filepath):
    """Extract top-level function names from a .js file."""
    try:
        with open(filepath) as f:
            source = f.read()
    except Exception:
        return None

    funcs = []
    # Match: function name(, const name = function, const name = (
    for match in re.finditer(
        r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:function|\())', source
    ):
        name = match.group(1) or match.group(2)
        if name and not name.startswith("_"):
            funcs.append(name)

    if not funcs:
        return None
    return {"exports": funcs}


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
    """Just note what page/component this CSS is for."""
    basename = os.path.splitext(os.path.basename(filepath))[0]
    return {"description": f"Styles for {basename}"}


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
            else:
                summary = None

            if summary:
                # Cap exports to keep file compact
                if "exports" in summary and len(summary["exports"]) > 8:
                    summary["exports"] = summary["exports"][:8]
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
