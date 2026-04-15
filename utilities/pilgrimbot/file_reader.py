"""Local codebase file reading for PilgrimBot — with safety filters + relevance scoring."""

import logging
import os

logger = logging.getLogger("pilgrimbot")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_FILE_CONTENT = 12000  # chars per file section to include in context

# Only read code files (no secrets, no configs, no data)
CODE_EXTS = {".py", ".js", ".css", ".html", ".md", ".json", ".sql", ".txt", ".yaml", ".yml", ".toml", ".cfg"}
SKIP_DIRS = {"venv_galactica", "archive", "antiquated_code", ".git", "__pycache__",
             "node_modules", ".claude", "testing", "tools/credentials"}


def read_local_file(filepath, max_chars=MAX_FILE_CONTENT, search_terms=None):
    """Read a code file from the local codebase.
    For large files, extracts the most relevant section using search_terms."""
    full_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.exists(full_path):
        return None
    # Safety: only read code files
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in CODE_EXTS:
        return None
    # Safety: skip sensitive directories
    if any(filepath.startswith(skip) or f"/{skip}" in filepath for skip in SKIP_DIRS):
        return None
    try:
        with open(full_path) as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"Local read error for {filepath}: {e}")
        return None
    if len(content) <= max_chars:
        return content
    # Large file — find the most relevant section
    if search_terms:
        best_pos = _find_best_section(content, search_terms)
        if best_pos is not None:
            start = max(0, best_pos - max_chars // 2)
            end = min(len(content), start + max_chars)
            snippet = content[start:end]
            prefix = "... [earlier code omitted] ...\n\n" if start > 0 else ""
            suffix = "\n\n... [later code omitted] ..." if end < len(content) else ""
            return prefix + snippet + suffix
    # Default: top of file
    return content[:max_chars] + "\n\n... [rest of file omitted] ..."


def _find_best_section(content, search_terms):
    """Find the position in content that has the most search term hits nearby."""
    content_lower = content.lower()
    positions = []
    idx = 0
    while True:
        pos = content_lower.find("\ndef ", idx)
        if pos == -1:
            break
        # Extract the function name
        line_end = content_lower.find("\n", pos + 5)
        func_line = content_lower[pos:line_end] if line_end > pos else ""
        # Check a larger window for this function (the whole function body)
        next_def = content_lower.find("\ndef ", pos + 5)
        window_end = next_def if next_def > 0 else len(content_lower)
        window = content_lower[pos:min(pos + 5000, window_end)]
        # Score: +3 for term in function name, +1 for term in body
        score = 0
        for term in search_terms:
            if term in func_line:
                score += 3
            elif term in window:
                score += 1
        if score > 0:
            positions.append((score, pos))
        idx = pos + 1
    if not positions:
        return None
    positions.sort(key=lambda x: -x[0])
    return positions[0][1]


def _build_codemap_summary(codemap):
    """Build a condensed codebase map for the system prompt (~8KB)."""
    lines = ["CODEBASE MAP (use read_file tool to fetch any file):"]
    for fpath, info in sorted(codemap.items()):
        desc = info.get("description", "")[:80]
        lines.append(f"  {fpath} — {desc}")
    return "\n".join(lines)
