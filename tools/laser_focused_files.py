#!/usr/bin/env python3
"""
Laser-Focused File Extractor for Pilgrims Mars Colony Game
Extracts only necessary files for specific development tasks.

Usage:
    python laser_focused_files.py --task add_colony_page
    python laser_focused_files.py --files app.py config.py
    python laser_focused_files.py --category frontend
"""
import os
import argparse
from datetime import datetime

# =============================================================================
# TASK PRESETS
# =============================================================================
TASK_PRESETS = {
    "add_colony_page": {
        "description": "Add new page to colony navigation",
        "files": [
            "app.py",
            "templates/colony/base_colony.html",
            "static/css/colony.css",
            "static/js/colony.js",
        ]
    },
    "add_arrival_page": {
        "description": "Add new page to arrival flow",
        "files": [
            "app.py",
            "templates/arrival/base_arrival.html",
            "static/css/arrival.css",
            "static/js/arrival.js",
        ]
    },
    "add_api_endpoint": {
        "description": "Add new API endpoint",
        "files": [
            "app.py",
            "static/js/core.js",
            "static/js/colony.js",
        ]
    },
    "modify_commander_stats": {
        "description": "Change commander stat mechanics",
        "files": [
            "config.py",
            "loader.py",
            "utilities/postgres_utils.py",
            "templates/colony/command.html",
        ]
    },
    "add_shop_item": {
        "description": "Add item to Supply Depot",
        "files": [
            "config.py",
            "utilities/depot_utils.py",
            "templates/colony/depot.html",
            "static/js/depot.js",
        ]
    },
    "modify_infrastructure": {
        "description": "Change infrastructure mechanics",
        "files": [
            "config.py",
            "utilities/infrastructure_utils.py",
            "utilities/postgres_utils.py",
            "templates/colony/infrastructure.html",
        ]
    },
    "modify_expeditions": {
        "description": "Modify expedition system",
        "files": [
            "config.py",
            "utilities/expedition_utils.py",
            "utilities/postgres_utils.py",
            "templates/colony/expeditions.html",
            "app.py",
        ]
    },
    "database_schema": {
        "description": "Modify database schema or queries",
        "files": [
            "utilities/postgres_utils.py",
            "app.py",
        ]
    },
    "blockchain": {
        "description": "Modify Sepolia blockchain integration",
        "files": [
            "utilities/sepolia_utils.py",
            "utilities/depot_utils.py",
            "utilities/expedition_utils.py",
            "app.py",
        ]
    },
    "ai_generation": {
        "description": "Modify image/video generation via Replicate",
        "files": [
            "utilities/replicate_utils.py",
            "utilities/google_cloud_storage_utils.py",
            "loader.py",
            "app.py",
        ]
    },
    "authentication": {
        "description": "Modify login/auth flow",
        "files": [
            "utilities/google_auth_utils.py",
            "utilities/postgres_utils.py",
            "app.py",
            "templates/base.html",
        ]
    },
    "discovery_items": {
        "description": "Generate or modify discovery items catalog",
        "files": [
            "tools/populate_discovery_items.py",
            "tools/populate_discovery_images.py",
            "utilities/claude_utils.py",
            "utilities/replicate_utils.py",
            "utilities/postgres_utils.py",
            "config.py",
        ]
    },
}

# =============================================================================
# FILE CATEGORIES
# =============================================================================
FILE_CATEGORIES = {
    "core": [
        "app.py",
        "config.py",
        "loader.py",
    ],
    "tools": [
        "tools/populate_discovery_items.py",
        "tools/populate_discovery_images.py",
    ],
    "utilities": [
        "utilities/depot_utils.py",
        "utilities/google_auth_utils.py",
        "utilities/google_cloud_storage_utils.py",
        "utilities/google_secret_utils.py",
        "utilities/infrastructure_utils.py",
        "utilities/postgres_utils.py",
        "utilities/sepolia_utils.py",
        "utilities/claude_utils.py",
    ],
    "frontend": [
        "static/css/core.css",
        "static/css/landing.css",
        "static/css/arrival.css",
        "static/css/colony.css",
        "static/js/core.js",
        "static/js/arrival.js",
        "static/js/colony.js",
        "static/js/depot.js",
    ],
    "css": [
        "static/css/core.css",
        "static/css/landing.css",
        "static/css/arrival.css",
        "static/css/colony.css",
    ],
    "js": [
        "static/js/core.js",
        "static/js/arrival.js",
        "static/js/colony.js",
        "static/js/depot.js",
    ],
    "templates": [
        "templates/base.html",
        "templates/landing.html",
        "templates/arrival/base_arrival.html",
        "templates/arrival/mining.html",
        "templates/arrival/commander.html",
        "templates/arrival/deploy.html",
        "templates/colony/base_colony.html",
        "templates/colony/dashboard.html",
        "templates/colony/command.html",
        "templates/colony/depot.html",
        "templates/colony/infrastructure.html",
        "templates/colony/expeditions.html",
        "templates/colony/profile.html",
    ],
    "arrival": [
        "templates/arrival/base_arrival.html",
        "templates/arrival/mining.html",
        "templates/arrival/commander.html",
        "templates/arrival/deploy.html",
        "static/css/arrival.css",
        "static/js/arrival.js",
    ],
    "colony": [
        "templates/colony/base_colony.html",
        "templates/colony/dashboard.html",
        "templates/colony/command.html",
        "templates/colony/depot.html",
        "templates/colony/infrastructure.html",
        "templates/colony/expeditions.html",
        "templates/colony/profile.html",
        "static/css/colony.css",
        "static/js/colony.js",
    ],
}

# =============================================================================
# FILE EXTRACTION
# =============================================================================
def read_file(filepath):
    """Read file with error handling"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"⚠️  Not found: {filepath}")
        return None
    except UnicodeDecodeError:
        print(f"⚠️  Encoding error: {filepath}")
        return None
    except Exception as e:
        print(f"⚠️  Error reading {filepath}: {e}")
        return None


def extract_files(file_list, output_file=None):
    """Extract files and write to output"""
    os.makedirs('lff', exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_file or f"lff/extracted_files_{timestamp}.txt"
    
    if not output_file.startswith('lff/'):
        output_file = f"lff/{output_file}"
    
    unique_files = []
    seen = set()
    for f in file_list:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    
    extracted_count = 0
    with open(output_file, 'w', encoding='utf-8') as out:
        out.write("=" * 80 + "\n")
        out.write("LASER-FOCUSED FILE EXTRACTION\n")
        out.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"Total Files: {len(unique_files)}\n")
        out.write("=" * 80 + "\n\n")
        
        out.write("FILES INCLUDED:\n")
        for filepath in unique_files:
            out.write(f"  • {filepath}\n")
        out.write("\n" + "=" * 80 + "\n")
        out.write("FILE CONTENTS\n")
        out.write("=" * 80 + "\n\n")
        
        for filepath in unique_files:
            contents = read_file(filepath)
            if contents:
                out.write(f"FILE: {filepath}\n")
                out.write("-" * 80 + "\n")
                out.write(contents)
                out.write("\n\n" + "=" * 80 + "\n\n")
                extracted_count += 1
        
        out.write(f"\n✅ Extracted {extracted_count}/{len(unique_files)} files\n")
    
    file_size_kb = os.path.getsize(output_file) / 1024
    print(f"\n✅ Extraction complete!")
    print(f"📄 Output: {output_file}")
    print(f"📊 Extracted: {extracted_count}/{len(unique_files)} files")
    print(f"💾 Size: {file_size_kb:.2f} KB")
    
    return output_file


def list_tasks():
    """Display all available task presets"""
    print("\n📋 AVAILABLE TASK PRESETS:\n")
    for task_id, task_info in TASK_PRESETS.items():
        print(f"  {task_id}")
        print(f"    {task_info['description']}")
        print(f"    Files ({len(task_info['files'])}):")
        for f in task_info['files']:
            print(f"      • {f}")
        print()


def list_categories():
    """Display all available file categories"""
    print("\n📂 AVAILABLE FILE CATEGORIES:\n")
    for cat_id, files in FILE_CATEGORIES.items():
        print(f"  {cat_id} ({len(files)} files)")
        for f in files:
            print(f"    • {f}")
        print()


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Extract files from Pilgrims Mars Colony Game for Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python laser_focused_files.py --task add_colony_page
  python laser_focused_files.py --files app.py config.py
  python laser_focused_files.py --category frontend
  python laser_focused_files.py --list-tasks
  python laser_focused_files.py --list-categories
        """
    )
    
    parser.add_argument('--task', choices=TASK_PRESETS.keys(), help='Preset task')
    parser.add_argument('--files', nargs='+', help='Specific file paths')
    parser.add_argument('--category', choices=FILE_CATEGORIES.keys(), help='File category')
    parser.add_argument('--list-tasks', action='store_true', help='List available tasks')
    parser.add_argument('--list-categories', action='store_true', help='List available categories')
    parser.add_argument('--output', help='Output filename')
    
    args = parser.parse_args()
    
    if args.list_tasks:
        list_tasks()
        return
    
    if args.list_categories:
        list_categories()
        return
    
    files_to_extract = []
    
    if args.task:
        task_info = TASK_PRESETS[args.task]
        print(f"\n🎯 Task: {task_info['description']}")
        files_to_extract = task_info['files']
    elif args.category:
        print(f"\n📂 Category: {args.category}")
        files_to_extract = FILE_CATEGORIES[args.category]
    elif args.files:
        print(f"\n📄 Custom files ({len(args.files)})")
        files_to_extract = args.files
    else:
        parser.print_help()
        return
    
    if files_to_extract:
        extract_files(files_to_extract, args.output)
    else:
        print("❌ No files to extract")


if __name__ == "__main__":
    main()