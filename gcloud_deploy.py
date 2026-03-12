#!/usr/bin/env python3
"""
Modern deployment script for Pilgrims Character Creation Game
Codename: Galactica | Live at: https://pilgri.ms
Follows Google Cloud best practices with full verbose output
FIXED: Better project switching and verification logic
"""
# ============================================================================
# MIGRATION NOTE (2026-03-12):
# This script is being replaced by the centralized deploy tool at:
#   ~/Desktop/code/master_gcp_deploy/deploy.py (symlinked to ~/.local/bin/deploy)
# Config for this project lives in: deploy.json (in this directory)
#
# New usage:  deploy "commit message"
# Old usage:  python gcloud_deploy.py
#
# This script still works but will be removed once migration is verified.
# See: ~/Desktop/code/master_gcp_deploy/ for full documentation.
# ============================================================================

from pathlib import Path
from typing import Optional
import subprocess
import json
import sys
import time
import os
import random
import string
import fcntl
import atexit

# Configuration
LOCKFILE = "/tmp/gcloud_deploy.lock"
PROJECT_ID = "galactica-character-game"  # GCP project ID (codename)
SERVICE = "default"
REGION = "us-central1"
MAX_VERSIONS = 3  # Keep only 3 versions for rollback
APP_NAME = "Pilgrims"
CUSTOM_DOMAIN = "https://pilgri.ms"


_lock_fd = None

def acquire_deploy_lock():
    """Acquire cross-project deploy lock. Waits if another deploy is running."""
    global _lock_fd
    _lock_fd = open(LOCKFILE, 'w')
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        try:
            with open(LOCKFILE, 'r') as f:
                holder = f.read().strip() or "unknown project"
        except Exception:
            holder = "unknown project"
        print(f"\n⏳ Waiting for deploy to finish: {holder}")
        print("   (deploys must be serial — they share the global gcloud config)")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX)
        print("   ✅ Lock acquired, proceeding.\n")
    _lock_fd.seek(0)
    _lock_fd.truncate()
    _lock_fd.write(f"{APP_NAME} ({PROJECT_ID}) - started {time.strftime('%H:%M:%S')}")
    _lock_fd.flush()
    atexit.register(release_deploy_lock)


def release_deploy_lock():
    """Release the deploy lock."""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except Exception:
            pass
        _lock_fd = None


def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    """
    Execute command with proper error handling.
    
    Args:
        cmd: Command and arguments as list
        capture: Whether to capture output
        
    Returns:
        CompletedProcess object with results
        
    Raises:
        SystemExit: If command fails
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Command failed: {' '.join(cmd)}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        sys.exit(1)


def header(text: str) -> None:
    """Print formatted section header."""
    print(f"\n{'='*70}\n{text}\n{'='*70}\n")


def verify_project() -> None:
    """
    Verify correct GCP project is active - CRITICAL SAFEGUARD.
    FIXED: Better retry logic and Application Default Credentials handling
    
    This prevents accidental deployment to wrong project which could
    overwrite production apps or incur unexpected costs.
    """
    header("🔍 Verifying Google Cloud Project Configuration")
    print(f"Expected project: {PROJECT_ID}")
    
    # First check current project
    result = run(["gcloud", "config", "get-value", "project"])
    current = result.stdout.strip()
    
    print(f"Current project:  {current}")
    
    if current != PROJECT_ID:
        print(f"\n⚠️  Current gcloud project is '{current}' but expected '{PROJECT_ID}'")
        print(f"Switching to the correct project...")
        
        # Try multiple methods to switch projects
        success = False
        
        # Method 1: Try existing configuration
        try:
            print("Method 1: Trying existing galactica-config configuration...")
            configs_result = run([
                "gcloud", "config", "configurations", "list",
                "--format=value(name)"
            ])
            configs = configs_result.stdout.strip().split('\n')
            
            if "galactica-config" in configs:
                print("  ✓ Found galactica-config, activating...")
                run(["gcloud", "config", "configurations", "activate", "galactica-config"])
                time.sleep(3)  # Allow config to take effect
                
                # Verify the switch worked
                result = run(["gcloud", "config", "get-value", "project"])
                current = result.stdout.strip()
                if current == PROJECT_ID:
                    success = True
                    print(f"  ✅ Successfully switched via configuration to {PROJECT_ID}")
                else:
                    print(f"  ❌ Configuration switch failed, still on {current}")
            
        except subprocess.CalledProcessError:
            print("  ❌ Configuration method failed")
        
        # Method 2: Direct project set
        if not success:
            try:
                print("Method 2: Setting project directly...")
                run(["gcloud", "config", "set", "project", PROJECT_ID])
                time.sleep(3)
                
                # Verify the switch worked
                result = run(["gcloud", "config", "get-value", "project"])
                current = result.stdout.strip()
                if current == PROJECT_ID:
                    success = True
                    print(f"  ✅ Successfully switched via direct set to {PROJECT_ID}")
                else:
                    print(f"  ❌ Direct set failed, still on {current}")
                    
            except subprocess.CalledProcessError:
                print("  ❌ Direct set method failed")
        
        # Method 3: Create new configuration
        if not success:
            try:
                print("Method 3: Creating new configuration...")
                run([
                    "gcloud", "config", "configurations", "create", "galactica-temp",
                    f"--project={PROJECT_ID}"
                ])
                run(["gcloud", "config", "configurations", "activate", "galactica-temp"])
                time.sleep(3)
                
                # Verify the switch worked
                result = run(["gcloud", "config", "get-value", "project"])
                current = result.stdout.strip()
                if current == PROJECT_ID:
                    success = True
                    print(f"  ✅ Successfully switched via new configuration to {PROJECT_ID}")
                    
            except subprocess.CalledProcessError:
                print("  ❌ New configuration method failed")
        
        if not success:
            print(f"\n🚨 CRITICAL ERROR: All methods failed to switch to project {PROJECT_ID}")
            print(f"Current project is still: {current}")
            print("\n⛔ DEPLOYMENT ABORTED to prevent deploying to wrong project!")
            print("\nPlease manually fix the project with:")
            print(f"  gcloud auth login")
            print(f"  gcloud config set project {PROJECT_ID}")
            print(f"  gcloud auth application-default set-quota-project {PROJECT_ID}")
            print("\nThen re-run this script.")
            sys.exit(1)
    else:
        print(f"✅ Project verification passed - correctly configured for {PROJECT_ID}")
    
    # Fix Application Default Credentials quota project if needed
    try:
        print("\n🔧 Checking Application Default Credentials...")
        run([
            "gcloud", "auth", "application-default", "set-quota-project", PROJECT_ID
        ])
        print(f"✅ Set ADC quota project to {PROJECT_ID}")
    except subprocess.CalledProcessError:
        print("⚠️  Could not set ADC quota project (may not be critical)")


def verify_files() -> None:
    """
    Verify required deployment files exist.
    
    Checks for essential files before attempting deployment to
    provide early failure and clear error messages.
    """
    required = {
        "app.yaml": "App Engine configuration",
        "requirements.txt": "Python dependencies",
        "app.py": "Main application"
    }
    
    print("\n📋 Verifying required files:")
    missing = []
    
    for file, desc in required.items():
        if Path(file).exists():
            print(f"  ✓ {file} ({desc})")
        else:
            print(f"  ✗ {file} ({desc}) - MISSING")
            missing.append(file)
    
    if missing:
        print(f"\n❌ Error: Missing required files: {', '.join(missing)}")
        sys.exit(1)


def get_versions() -> list[dict]:
    """
    Fetch existing App Engine versions.
    
    Returns:
        List of version dictionaries sorted by creation time (newest first)
    """
    print(f"🔍 Checking existing versions for service: {SERVICE}...")
    try:
        result = run([
            "gcloud", "app", "versions", "list",
            f"--service={SERVICE}",
            "--format=json",
            f"--project={PROJECT_ID}"
        ])
        versions = json.loads(result.stdout)
        versions.sort(key=lambda x: x["version"]["createTime"], reverse=True)
        return versions
    except subprocess.CalledProcessError as e:
        error_msg = str(e.stderr) if e.stderr else ""
        if "Service not found" in error_msg or f"Service [{SERVICE}] not found" in error_msg:
            print(f"ℹ️  Service {SERVICE} not found. It will be created during deployment.")
            return []
        else:
            print(f"❌ Error getting versions: {error_msg}")
            raise e


def cleanup_versions(versions: list[dict]) -> None:
    """
    Delete old versions beyond the configured limit.
    
    Maintains version history for rollback while preventing
    unlimited version accumulation and associated storage costs.
    
    Args:
        versions: List of all versions (newest first)
    """
    if len(versions) <= MAX_VERSIONS:
        return
    
    to_delete = versions[MAX_VERSIONS:]
    header(f"🗑️  Cleaning Up Old Versions ({len(to_delete)} to delete)")
    
    for v in to_delete:
        version_id = v["id"]
        print(f"  Deleting: {SERVICE}/{version_id}")
        run([
            "gcloud", "app", "versions", "delete", version_id,
            f"--service={SERVICE}",
            "--quiet",
            f"--project={PROJECT_ID}"
        ])
    
    print(f"✅ Cleaned up {len(to_delete)} old version(s)")


def get_changed_files(directory: str = ".") -> list[str]:
    """
    Get list of new or modified files using git diff.
    
    Args:
        directory: Directory to check for changes
        
    Returns:
        List of changed file paths
    """
    try:
        result = subprocess.run(
            ["git", "-C", directory, "diff", "--name-only", "HEAD^", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        files = result.stdout.strip().split("\n")
        return [os.path.join(directory, f) for f in files if f]
    except subprocess.CalledProcessError:
        # Not an error - normal for first deployment or non-git repos
        return []


def list_files_to_upload() -> int:
    """
    List files that will be uploaded to Google Cloud Storage.
    
    Respects .gcloudignore patterns to show accurate deployment manifest.
    
    Returns:
        Count of files to be uploaded
    """
    print("📦 Files to be uploaded:")
    
    # Parse .gcloudignore
    ignored_patterns = set()
    if os.path.exists('.gcloudignore'):
        with open('.gcloudignore', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ignored_patterns.add(line.rstrip('/'))
    
    # Default ignore patterns if no .gcloudignore exists
    if not ignored_patterns:
        ignored_patterns = {
            '.git', 'logging', '__pycache__', '*.pyc', '.env', 'venv*', 
            '.vscode', '.idea', '*.md', 'gather_pythons.py', 
            '*_project_structure.txt', 'deploy.py', 'test_crew'
        }
    
    def should_ignore(path: str) -> bool:
        """Check if a path should be ignored based on patterns."""
        for pattern in ignored_patterns:
            if pattern.endswith('*'):
                if path.startswith(pattern[:-1]):
                    return True
            elif pattern.startswith('*'):
                if path.endswith(pattern[1:]):
                    return True
            elif path == pattern or path.startswith(pattern + '/'):
                return True
        return False
    
    # Walk directory and respect .gcloudignore patterns
    files_to_upload = []
    for root, dirs, files in os.walk('.'):
        # Filter directories
        dirs[:] = [d for d in dirs if not should_ignore(d)]
        
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), '.')
            if not should_ignore(rel_path) and not should_ignore(file):
                files_to_upload.append(rel_path)
    
    # Print the files (limit output for large deployments)
    sorted_files = sorted(files_to_upload)
    if len(sorted_files) <= 50:
        for file in sorted_files:
            print(f"  • {file}")
    else:
        for file in sorted_files[:25]:
            print(f"  • {file}")
        print(f"  ... and {len(sorted_files) - 50} more files ...")
        for file in sorted_files[-25:]:
            print(f"  • {file}")
    
    print(f"\n📊 Total files to upload: {len(files_to_upload)}")
    return len(files_to_upload)


def generate_version_name() -> str:
    """
    Generate random version name for App Engine.
    
    Format: version-{10-char-random-string}
    Uses lowercase letters and digits for URL compatibility.
    
    Returns:
        Version name string
    """
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"version-{random_string}"


def deploy() -> float:
    """
    Deploy application to App Engine with full verbose output.
    
    This is the main deployment function that:
    1. Verifies project and files
    2. Shows changed files
    3. Lists deployment manifest
    4. Deploys with real-time output
    5. Cleans up old versions
    
    Returns:
        Elapsed deployment time in seconds
    """
    start = time.time()
    current_directory = os.path.dirname(os.path.abspath("app.yaml"))
    
    header(f"🚀 DEPLOYING {APP_NAME.upper()} CHARACTER CREATION TO GOOGLE APP ENGINE")
    print(f"App Name:     {APP_NAME}")
    print(f"Project ID:   {PROJECT_ID}")
    print(f"Service:      {SERVICE}")
    print(f"Region:       {REGION}")
    print(f"Deploy from:  {current_directory}")
    print(f"Config file:  app.yaml")
    print(f"Custom Domain: {CUSTOM_DOMAIN}")
    
    # Pre-deployment checks
    verify_project()
    verify_files()
    
    # List changed files
    header("📝 Changed Files Since Last Commit")
    changed_files = get_changed_files(current_directory)
    if changed_files:
        for file_path in changed_files:
            print(f"  • {file_path}")
    else:
        print("  ℹ️  No git changes detected (normal for first deployment or non-git repo)")
    
    # Check existing versions
    try:
        versions = get_versions()
        print(f"✅ Found {len(versions)} existing version(s)")
    except subprocess.CalledProcessError as e:
        versions = []
        print(f"⚠️  Could not retrieve versions (likely first deployment)")
    
    if versions:
        print(f"📌 Latest version: {versions[0]['id']}")
    else:
        print(f"📌 This will be the first deployment for {SERVICE}")
    
    if len(versions) > MAX_VERSIONS:
        print(f"⚠️  More than {MAX_VERSIONS} versions exist - will clean up after deployment")
    
    # Show deployment manifest
    header("📦 Deployment Manifest")
    file_count = list_files_to_upload()
    
    # Generate version name
    version_name = generate_version_name()
    
    header(f"🚀 Starting Deployment: {version_name}")
    print(f"Version: {version_name}")
    print(f"Time:    {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n" + "=" * 70)
    print("DEPLOYMENT PROGRESS - LIVE OUTPUT")
    print("=" * 70 + "\n")
    
    try:
        # Deploy with real-time streaming output
        process = subprocess.Popen(
            [
                "gcloud", "app", "deploy", "app.yaml",
                f"--project={PROJECT_ID}",
                f"--version={version_name}",
                "--verbosity=info",
                "--quiet",  # NO PROMPTS - fully automatic
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1  # Line buffered for real-time output
        )
        
        # Stream output line by line
        for line in process.stdout:
            print(line, end='')
        
        # Check return code
        return_code = process.wait()
        
        if return_code != 0:
            print(f"\n❌ Deployment failed with return code {return_code}")
            sys.exit(1)
        
        print("\n" + "=" * 70)
        print("✅ DEPLOYMENT COMPLETED SUCCESSFULLY")
        print("=" * 70 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Deployment cancelled by user (Ctrl+C)")
        process.terminate()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Deployment error: {e}")
        sys.exit(1)
    
    # Deploy cron.yaml if it exists
    if Path("cron.yaml").exists():
        print("\n" + "=" * 70)
        print("⏰ DEPLOYING CRON JOBS")
        print("=" * 70 + "\n")

        try:
            cron_process = subprocess.Popen(
                [
                    "gcloud", "app", "deploy", "cron.yaml",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in cron_process.stdout:
                print(line, end='')

            cron_return = cron_process.wait()
            if cron_return == 0:
                print("✅ Cron jobs deployed successfully")
            else:
                print(f"⚠️  Cron deployment returned code {cron_return}")

        except Exception as e:
            print(f"⚠️  Could not deploy cron.yaml: {e}")

    # Post-deployment cleanup
    if len(versions) > MAX_VERSIONS:
        try:
            updated_versions = get_versions()
            cleanup_versions(updated_versions)
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Could not clean up old versions: {e.stderr}")
    
    elapsed = time.time() - start
    
    # Deployment summary
    header("✅ DEPLOYMENT SUMMARY")
    print(f"⏱️  Deployment Time: {elapsed:.2f} seconds ({elapsed/60:.1f} minutes)")
    print(f"📦 Files Deployed:  {file_count}")
    print(f"🏷️  Version Name:    {version_name}")
    print(f"\n🌐 Your {APP_NAME} app is now LIVE at:")
    print(f"  • {CUSTOM_DOMAIN} (custom domain)")
    print(f"  • https://{PROJECT_ID}.appspot.com (App Engine URL)")
    print(f"  • https://{version_name}-dot-{PROJECT_ID}.appspot.com (this version)")
    
    return elapsed


def tail_logs() -> None:
    """
    Stream application logs in real-time, filtering out ALTS warnings.

    Press Ctrl+C to stop tailing.
    """
    print("\n" + "=" * 70)
    print(f"📊 TAILING LOGS FOR {APP_NAME}")
    print("=" * 70)
    print("ℹ️  Press Ctrl+C to stop\n", flush=True)

    try:
        process = subprocess.Popen(
            [
                "gcloud", "app", "logs", "tail",
                f"--service={SERVICE}",
                f"--project={PROJECT_ID}"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress ALTS warnings
            text=True,
            bufsize=0  # Unbuffered for real-time output
        )

        # Filter out noise from stdout - flush each line immediately
        for line in process.stdout:
            # Skip ALTS warnings and "Waiting" messages
            if any(skip in line for skip in ["ALTS creds ignored", "alts_credentials.cc", "Waiting for new log entries"]):
                continue
            print(line, end='', flush=True)

    except KeyboardInterrupt:
        process.terminate()
        print("\n\n⏹️  Stopped tailing logs")
        print(f"\n💡 Resume anytime with:")
        print(f"   gcloud app logs tail -s {SERVICE} --project {PROJECT_ID} 2>/dev/null")


def main() -> None:
    """
    Main deployment orchestration.

    Coordinates the full deployment workflow:
    1. Deploy application
    2. Exit (log tailing handled by git_push.sh for better real-time output)
    """
    print(f"\n🎮 {APP_NAME} Deployment Script")
    print(f"Codename: Galactica")
    print(f"Keeping {MAX_VERSIONS} versions for rollback capability\n")

    # Acquire cross-project deploy lock (waits if another deploy is running)
    acquire_deploy_lock()

    try:
        elapsed = deploy()
        # Log tailing moved to git_push.sh for better real-time output
        print(f"\n💡 To tail logs: gcloud app logs tail -s {SERVICE} --project {PROJECT_ID} 2>/dev/null")

    except KeyboardInterrupt:
        print("\n\n⚠️  Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()