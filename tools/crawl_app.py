#!/usr/bin/env python3
"""
Flask App File Mapper - READ ONLY - DOCUMENTATION TOOL
Maps your Flask app structure and documents all files.
DOES NOT MODIFY ANY FILES - purely analytical/read-only operation.
NO DELETION SUGGESTIONS - just maps dependencies and extracts documentation.
"""

import os
import re
import json
from pathlib import Path
from typing import Set, Dict, List

# ============================================================================
# GLOBAL CONFIGURATION - CUSTOMIZE THESE FOR YOUR PROJECT
# ============================================================================

# Main entry point file for your Flask app
MAIN_APP_FILE = "app.py"  # Change to "main.py", "run.py", etc.

# Directories to completely ignore during crawl
IGNORE_DIRECTORIES = {
    '__pycache__',
    'node_modules',
    '.pytest_cache',
    '.vscode',
    '.idea',
    '.git',
    'venv',
    '.env',
}

# Directory name patterns to ignore (directories starting with these strings)
IGNORE_DIRECTORY_PATTERNS = [
    'venv_',      # Any virtualenv like venv_dev, venv_prod
    'env_',       # Any env directory
    '.',          # Any hidden directory (already covered by .git, but catches others)
]

# File extensions to scan for dependencies
SCANNABLE_EXTENSIONS = {
    '.py',        # Python files
    '.html',      # HTML templates
    '.htm',       # HTML templates (alternate)
    '.css',       # Stylesheets
    '.js',        # JavaScript
}

# File extensions to look for as data/resource files
DATA_FILE_EXTENSIONS = [
    '.csv',
    '.json',
    '.txt',
    '.yaml',
    '.yml',
    '.xml',
    '.ini',
    '.cfg',
]

# Flask-specific directory structure (relative to app root)
TEMPLATE_DIRECTORIES = [
    'templates',
    'views',
    'app/templates',
]

STATIC_DIRECTORIES = [
    'static',
    'assets',
    'public',
    'app/static',
]

STATIC_SUBDIRECTORIES = [
    'css',
    'js',
    'images',
    'img',
    'fonts',
    'files',
    'media',
]

# Output report filename
OUTPUT_REPORT_FILE = "app_structure_map.json"

# Enable verbose output during crawling
VERBOSE_OUTPUT = True

# Extract file documentation (first comment/docstring) for context
EXTRACT_FILE_DOCS = True

# Number of lines to read from start of file to find documentation
DOC_SEARCH_LINES = 15

# ============================================================================
# END OF CONFIGURATION
# ============================================================================


class AppMapper:
    def __init__(self, app_root: str):
        self.app_root = Path(app_root)
        self.dependency_chain: Set[Path] = set()
        self.all_project_files: Set[Path] = set()
        self.file_references: Dict[str, List[str]] = {}
        self.processed_files: Set[Path] = set()
        self.file_documentation: Dict[str, str] = {}
    
    def _should_ignore_path(self, path: Path) -> bool:
        """Check if a path should be ignored based on configuration"""
        path_str = str(path)
        
        for part in path.parts:
            if part in IGNORE_DIRECTORIES:
                return True
            
            for pattern in IGNORE_DIRECTORY_PATTERNS:
                if part.startswith(pattern):
                    return True
        
        return False
    
    def _log(self, message: str, level: str = "info"):
        """Log message if verbose output is enabled"""
        if VERBOSE_OUTPUT:
            icons = {
                "info": "📄",
                "found": "🔗",
                "warning": "⚠️",
                "error": "❌",
                "success": "✅",
            }
            icon = icons.get(level, "ℹ️")
            print(f"{icon} {message}")
    
    def _extract_file_documentation(self, file_path: Path) -> str:
        """Extract documentation from the beginning of a file"""
        if not EXTRACT_FILE_DOCS:
            return ""
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= DOC_SEARCH_LINES:
                        break
                    lines.append(line)
            
            content = ''.join(lines)
            
            # Python files - look for docstrings
            if file_path.suffix == '.py':
                # Look for triple-quoted docstrings at the start
                docstring_patterns = [
                    r'^\s*"""(.*?)"""',  # Triple double quotes
                    r"^\s*'''(.*?)'''",  # Triple single quotes
                ]
                
                for pattern in docstring_patterns:
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        doc = match.group(1).strip()
                        return doc
                
                # If no docstring, look for initial comment block
                comment_lines = []
                in_comment_block = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        in_comment_block = True
                        comment_lines.append(stripped[1:].strip())
                    elif in_comment_block and stripped == '':
                        continue
                    elif in_comment_block:
                        break
                
                if comment_lines:
                    return '\n'.join(comment_lines)
            
            # HTML files - look for initial comments
            elif file_path.suffix in ['.html', '.htm']:
                comment_match = re.search(r'<!--\s*(.*?)\s*-->', content, re.DOTALL)
                if comment_match:
                    return comment_match.group(1).strip()
            
            # CSS files - look for initial comments
            elif file_path.suffix == '.css':
                comment_match = re.search(r'/\*\s*(.*?)\s*\*/', content, re.DOTALL)
                if comment_match:
                    return comment_match.group(1).strip()
            
            # JavaScript files - look for initial comments
            elif file_path.suffix == '.js':
                multi_match = re.search(r'/\*\s*(.*?)\s*\*/', content, re.DOTALL)
                if multi_match:
                    return multi_match.group(1).strip()
                
                comment_lines = []
                in_comment_block = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('//'):
                        in_comment_block = True
                        comment_lines.append(stripped[2:].strip())
                    elif in_comment_block and stripped == '':
                        continue
                    elif in_comment_block:
                        break
                
                if comment_lines:
                    return '\n'.join(comment_lines)
            
            return ""
            
        except Exception as e:
            self._log(f"Error extracting docs from {file_path}: {e}", "warning")
            return ""
        
    def map_all(self, starting_file: str = None) -> Dict:
        """Main mapping function - maps dependency chain starting from entry point"""
        if starting_file is None:
            starting_file = MAIN_APP_FILE
            
        print(f"🗺️  Starting app structure mapping from {starting_file}...")
        
        start_path = self.app_root / starting_file
        if not start_path.exists():
            print(f"❌ Starting file {start_path} not found!")
            return {}
        
        # First, get all files in project
        self._discover_all_files()
        
        # Then trace dependency chain
        files_to_process = [start_path]
        iteration = 0
        
        while files_to_process:
            iteration += 1
            print(f"\n🔄 Dependency mapping iteration {iteration}...")
            
            current_batch = files_to_process.copy()
            files_to_process.clear()
            
            for current_file in current_batch:
                if current_file in self.processed_files:
                    continue
                    
                if self._should_ignore_path(current_file):
                    continue
                
                if not current_file.exists():
                    continue
                    
                self.processed_files.add(current_file)
                self.dependency_chain.add(current_file)
                
                # Extract file documentation
                if EXTRACT_FILE_DOCS:
                    relative_path = str(current_file.relative_to(self.app_root))
                    doc = self._extract_file_documentation(current_file)
                    if doc:
                        self.file_documentation[relative_path] = doc
                
                self._log(f"Processing: {current_file.relative_to(self.app_root)}")
                
                # Process file based on type - ALL file types can reference other files
                new_files = []
                if current_file.suffix == '.py':
                    new_files = self._map_python_file(current_file)
                elif current_file.suffix in ['.html', '.htm']:
                    new_files = self._map_html_file(current_file)
                elif current_file.suffix == '.css':
                    new_files = self._map_css_file(current_file)
                elif current_file.suffix == '.js':
                    new_files = self._map_js_file(current_file)
                else:
                    # Still track non-scannable files but don't process them
                    relative = str(current_file.relative_to(self.app_root))
                    if relative not in self.file_references:
                        self.file_references[relative] = []
                
                # Add newly found files to processing queue
                for new_file in new_files:
                    if (new_file not in self.processed_files and 
                        new_file not in files_to_process and
                        not self._should_ignore_path(new_file)):
                        files_to_process.append(new_file)
            
            print(f"   Found {len(files_to_process)} new files to process...")
        
        print(f"\n✅ Mapping complete after {iteration} iterations!")
        return self._generate_report()
    
    def _discover_all_files(self):
        """Discover all files in the project"""
        print("📁 Discovering all project files...")
        
        for root, dirs, files in os.walk(self.app_root):
            # Remove ignored directories from traversal
            dirs_to_remove = []
            for d in dirs:
                dir_path = Path(root) / d
                if self._should_ignore_path(dir_path):
                    dirs_to_remove.append(d)
            
            for d in dirs_to_remove:
                dirs.remove(d)
            
            for file in files:
                if not file.startswith('.') and not file.endswith('.pyc'):
                    file_path = Path(root) / file
                    if not self._should_ignore_path(file_path):
                        self.all_project_files.add(file_path)
        
        print(f"   Found {len(self.all_project_files)} total files")
    
    def _map_python_file(self, file_path: Path) -> List[Path]:
        """Extract ALL references from Python files"""
        new_files = []
        
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []
            
            # Find Python imports
            import_patterns = [
                r'from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import',
                r'import\s+([a-zA-Z_][a-zA-Z0-9_.]*)',
                r'from\s+\.([a-zA-Z_][a-zA-Z0-9_.]*)\s+import',
                r'from\s+\.\.([a-zA-Z_][a-zA-Z0-9_.]*)\s+import',
            ]
            
            for pattern in import_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    module_parts = match.split('.')
                    
                    possible_paths = [
                        file_path.parent / f"{module_parts[0]}.py",
                        file_path.parent / f"{module_parts[0]}/__init__.py",
                        self.app_root / f"{'/'.join(module_parts)}.py",
                        self.app_root / f"{'/'.join(module_parts)}/__init__.py",
                        self.app_root / "utilities" / f"{module_parts[0]}.py",
                        self.app_root / f"{match.replace('.', '/')}.py",
                    ]
                    
                    for possible_path in possible_paths:
                        if possible_path.exists():
                            new_files.append(possible_path)
                            self.file_references[relative_path].append(
                                str(possible_path.relative_to(self.app_root))
                            )
                            break
            
            # Find template references
            template_patterns = [
                r"render_template\(\s*['\"]([^'\"]+)['\"]",
            ]
            
            for pattern in template_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    possible_paths = [self.app_root / match]
                    
                    for template_dir in TEMPLATE_DIRECTORIES:
                        possible_paths.append(self.app_root / template_dir / match)
                    
                    for possible_path in possible_paths:
                        if possible_path.exists():
                            new_files.append(possible_path)
                            self.file_references[relative_path].append(
                                str(possible_path.relative_to(self.app_root))
                            )
                            break
            
            # Find static file references
            static_patterns = [
                r"url_for\(\s*['\"]static['\"],\s*filename\s*=\s*['\"]([^'\"]+)['\"]",
            ]
            
            for pattern in static_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    for static_dir in STATIC_DIRECTORIES:
                        static_path = self.app_root / static_dir / match
                        if static_path.exists():
                            new_files.append(static_path)
                            self.file_references[relative_path].append(
                                f"{static_dir}/{match}"
                            )
                            break
            
            # Find data file references
            for ext in DATA_FILE_EXTENSIONS:
                pattern = rf"['\"]([^'\"]+\{ext})['\"]"
                matches = re.findall(pattern, content)
                for match in matches:
                    if '{' in match or '%' in match:
                        continue
                        
                    possible_paths = [
                        self.app_root / match,
                        file_path.parent / match,
                    ]
                    
                    for static_dir in STATIC_DIRECTORIES:
                        possible_paths.append(self.app_root / static_dir / match)
                        for subdir in STATIC_SUBDIRECTORIES:
                            possible_paths.append(
                                self.app_root / static_dir / subdir / match
                            )
                    
                    for possible_path in possible_paths:
                        if possible_path.exists():
                            new_files.append(possible_path)
                            self.file_references[relative_path].append(
                                str(possible_path.relative_to(self.app_root))
                            )
                            break
                        
        except Exception as e:
            self._log(f"Error reading {file_path}: {e}", "error")
        
        return new_files
    
    def _map_html_file(self, file_path: Path) -> List[Path]:
        """Extract ALL references from HTML files"""
        new_files = []
        
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []
            
            patterns = [
                (r'<link[^>]*href\s*=\s*["\']([^"\']+)["\']', 'link'),
                (r'<link[^>]*href\s*=\s*([^\s>]+)', 'link-noquote'),  # Without quotes
                (r'<script[^>]*src\s*=\s*["\']([^"\']+)["\']', 'script'),
                (r'<script[^>]*src\s*=\s*([^\s>]+)', 'script-noquote'),  # Without quotes
                (r'<img[^>]*src\s*=\s*["\']([^"\']+)["\']', 'image'),
                (r'<source[^>]*src\s*=\s*["\']([^"\']+)["\']', 'source'),
                (r'<audio[^>]*src\s*=\s*["\']([^"\']+)["\']', 'audio'),
                (r'<video[^>]*src\s*=\s*["\']([^"\']+)["\']', 'video'),
                (r'<iframe[^>]*src\s*=\s*["\']([^"\']+)["\']', 'iframe'),
                (r'{%\s*extends\s+["\']([^"\']+)["\']', 'template-extends'),
                (r'{%\s*include\s+["\']/?([^"\']+)["\']', 'template-include'),
                (r'{{\s*url_for\s*\(\s*["\']static["\'],\s*filename\s*=\s*["\']([^"\']+)["\']\s*\)\s*}}', 'flask-static'),
                (r'url_for\s*\(\s*["\']static["\'],\s*filename\s*=\s*["\']([^"\']+)["\']\s*\)', 'flask-static'),
                (r'url\(["\']?([^"\')\s]+)["\']?\)', 'css-url'),
            ]
            
            for pattern, ref_type in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    # Skip external URLs, data URLs, and template variables
                    if '{{' in match or '{%' in match:
                        continue
                    
                    if match.startswith(('http://', 'https://', '//', 'data:', '#', 'javascript:')):
                        continue
                    
                    # Handle direct /static/ paths (common in base templates)
                    if match.startswith('/static/'):
                        # Remove leading /static/ to get relative path
                        static_relative = match[8:]  # Remove '/static/'
                        for static_dir in STATIC_DIRECTORIES:
                            static_path = self.app_root / static_dir / static_relative
                            if static_path.exists():
                                new_files.append(static_path)
                                self.file_references[relative_path].append(
                                    str(static_path.relative_to(self.app_root))
                                )
                                self._log(f"Found static path: {static_dir}/{static_relative}", "found")
                                break
                        continue
                    
                    if ref_type == 'flask-static':
                        for static_dir in STATIC_DIRECTORIES:
                            static_path = self.app_root / static_dir / match
                            if static_path.exists():
                                new_files.append(static_path)
                                self.file_references[relative_path].append(
                                    str(static_path.relative_to(self.app_root))
                                )
                                self._log(f"Found Flask static: {static_dir}/{match}", "found")
                                break
                        continue
                    
                    possible_paths = []
                    
                    if ref_type in ['template-extends', 'template-include']:
                        possible_paths = [
                            file_path.parent / match,
                            self.app_root / match,
                        ]
                        for template_dir in TEMPLATE_DIRECTORIES:
                            possible_paths.append(self.app_root / template_dir / match)
                        
                        for possible_path in possible_paths:
                            if possible_path.exists():
                                new_files.append(possible_path)
                                self.file_references[relative_path].append(
                                    str(possible_path.relative_to(self.app_root))
                                )
                                self._log(f"Found template: {possible_path.relative_to(self.app_root)}", "found")
                                break
                    else:
                        possible_paths = [
                            file_path.parent / match,
                            self.app_root / match,
                        ]
                        
                        for static_dir in STATIC_DIRECTORIES:
                            possible_paths.append(self.app_root / static_dir / match)
                            for subdir in STATIC_SUBDIRECTORIES:
                                possible_paths.append(
                                    self.app_root / static_dir / subdir / match
                                )
                        
                        for possible_path in possible_paths:
                            if possible_path.exists():
                                new_files.append(possible_path)
                                self.file_references[relative_path].append(
                                    str(possible_path.relative_to(self.app_root))
                                )
                                self._log(f"Found asset: {possible_path.relative_to(self.app_root)}", "found")
                                break
                            
        except Exception as e:
            self._log(f"Error reading {file_path}: {e}", "error")
        
        return new_files
    
    def _map_css_file(self, file_path: Path) -> List[Path]:
        """Extract ALL references from CSS files"""
        new_files = []
        
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []
            
            patterns = [
                r'@import\s+["\']([^"\']+)["\']',
                r'@import\s+url\(["\']?([^"\')\s]+)["\']?\)',
                r'url\(["\']?([^"\')\s]+)["\']?\)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    if match.startswith(('http://', 'https://', 'data:', '#')):
                        continue
                    
                    possible_paths = [
                        file_path.parent / match,
                        self.app_root / match,
                    ]
                    
                    for static_dir in STATIC_DIRECTORIES:
                        possible_paths.append(self.app_root / static_dir / match)
                        for subdir in STATIC_SUBDIRECTORIES:
                            possible_paths.append(
                                self.app_root / static_dir / subdir / match
                            )
                    
                    for possible_path in possible_paths:
                        if possible_path.exists():
                            new_files.append(possible_path)
                            self.file_references[relative_path].append(
                                str(possible_path.relative_to(self.app_root))
                            )
                            break
                            
        except Exception as e:
            self._log(f"Error reading {file_path}: {e}", "error")
        
        return new_files
    
    def _map_js_file(self, file_path: Path) -> List[Path]:
        """Extract ALL references from JavaScript files"""
        new_files = []
        
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []
            
            patterns = [
                r'import\s+.*from\s+["\']([^"\']+)["\']',
                r'import\s+["\']([^"\']+)["\']',
                r'require\(["\']([^"\']+)["\']\)',
                r'import\(["\']([^"\']+)["\']\)',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    if match.startswith(('http://', 'https://')):
                        continue
                    
                    if match.startswith('../'):
                        resolved_path = file_path.parent.parent / match[3:]
                    elif match.startswith('./'):
                        resolved_path = file_path.parent / match[2:]
                    else:
                        resolved_path = None
                    
                    possible_paths = []
                    if resolved_path:
                        possible_paths.append(resolved_path)
                        if not resolved_path.suffix:
                            possible_paths.append(resolved_path.with_suffix('.js'))
                    
                    possible_paths.extend([
                        file_path.parent / f"{match}.js",
                        file_path.parent / match,
                        self.app_root / f"{match}.js",
                        self.app_root / match,
                    ])
                    
                    for static_dir in STATIC_DIRECTORIES:
                        possible_paths.extend([
                            self.app_root / static_dir / f"{match}.js",
                            self.app_root / static_dir / match,
                        ])
                        for subdir in ['js', 'scripts']:
                            possible_paths.extend([
                                self.app_root / static_dir / subdir / f"{match}.js",
                                self.app_root / static_dir / subdir / match,
                            ])
                    
                    for possible_path in possible_paths:
                        if possible_path and possible_path.exists():
                            new_files.append(possible_path)
                            self.file_references[relative_path].append(
                                str(possible_path.relative_to(self.app_root))
                            )
                            self._log(f"Found JS dependency: {possible_path.relative_to(self.app_root)}", "found")
                            break
                            
        except Exception as e:
            self._log(f"Error reading {file_path}: {e}", "error")
        
        return new_files
    
    def _generate_report(self) -> Dict:
        """Generate the final mapping report"""
        dependency_chain_list = sorted([
            str(f.relative_to(self.app_root)) for f in self.dependency_chain
        ])
        
        all_files_list = sorted([
            str(f.relative_to(self.app_root)) for f in self.all_project_files
        ])
        
        # CRITICAL: Files in dependency chain should NOT be in files_not_in_chain
        files_not_in_chain = sorted([
            f for f in all_files_list if f not in dependency_chain_list
        ])
        
        report = {
            'summary': {
                'total_project_files': len(all_files_list),
                'files_in_dependency_chain': len(dependency_chain_list),
                'files_not_in_dependency_chain': len(files_not_in_chain),
                'documentation_extracted': len(self.file_documentation)
            },
            'dependency_chain': dependency_chain_list,
            'files_not_in_chain': files_not_in_chain,
            'all_project_files': all_files_list,
            'file_references': self.file_references,
            'file_documentation': self.file_documentation
        }
        
        return report


def main():
    """Run the mapper - READ ONLY documentation operation"""
    print("🗺️  FLASK APP MAPPER & DOCUMENTATION TOOL - READ ONLY")
    print("📖 Maps your app structure and extracts file documentation")
    print(f"🚫 Ignoring: {', '.join(sorted(IGNORE_DIRECTORIES))}")
    print()
    
    # Use current directory automatically
    app_root = os.path.abspath(".")
    
    if not os.path.exists(app_root):
        print(f"❌ Directory {app_root} not found!")
        return
    
    mapper = AppMapper(app_root)
    
    # Check if configured main file exists
    main_file_path = os.path.join(app_root, MAIN_APP_FILE)
    if not os.path.exists(main_file_path):
        print(f"❌ Main file '{MAIN_APP_FILE}' not found!")
        print(f"💡 Update MAIN_APP_FILE in the configuration section")
        return
    
    print(f"🚀 Starting app structure mapping from {MAIN_APP_FILE}...")
    print("📊 Tracing dependency chain and documenting all files...")
    report = mapper.map_all(MAIN_APP_FILE)
    
    if not report:
        print("❌ Mapping failed!")
        return
    
    # Save detailed report
    output_file = OUTPUT_REPORT_FILE
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print("\n" + "="*70)
    print("📊 APP STRUCTURE MAP")
    print("="*70)
    print(f"📁 Total files in project: {report['summary']['total_project_files']}")
    print(f"🔗 Files in dependency chain: {report['summary']['files_in_dependency_chain']}")
    print(f"📄 Files not in dependency chain: {report['summary']['files_not_in_dependency_chain']}")
    print(f"📝 Files with documentation: {report['summary']['documentation_extracted']}")
    
    print(f"\n✅ Complete mapping saved to: {output_file}")
    
    # Show dependency chain breakdown by type
    chain_files = report['dependency_chain']
    py_files = [f for f in chain_files if f.endswith('.py')]
    html_files = [f for f in chain_files if f.endswith('.html') or f.endswith('.htm')]
    css_files = [f for f in chain_files if f.endswith('.css')]
    js_files = [f for f in chain_files if f.endswith('.js')]
    other_files = [f for f in chain_files if f not in py_files + html_files + css_files + js_files]
    
    print(f"\n📋 Dependency Chain Breakdown:")
    print(f"   🐍 Python files: {len(py_files)}")
    print(f"   📄 HTML templates: {len(html_files)}")
    print(f"   🎨 CSS files: {len(css_files)}")
    print(f"   ⚡ JavaScript files: {len(js_files)}")
    if other_files:
        print(f"   📦 Other files: {len(other_files)}")
    
    print("📖 This tool is READ-ONLY - no files were modified or deleted.")


if __name__ == "__main__":
    main()