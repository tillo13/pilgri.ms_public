#!/bin/bash
# ============================================================================
# MIGRATION NOTE (2026-03-12):
# This script is being replaced by the centralized deploy tool at:
#   ~/Desktop/code/master_gcp_deploy/deploy.py (symlinked to ~/.local/bin/deploy)
# Config for this project lives in: deploy.json (in this directory)
#
# New usage:  deploy "commit message"
# Old usage:  ./git_push.sh "commit message"
#
# This script still works but will be removed once migration is verified.
# See: ~/Desktop/code/master_gcp_deploy/ for full documentation.
# ============================================================================

# PILGRIMS PROJECT CONFIGURATION - CRITICAL SAFEGUARDS
EXPECTED_PROJECT="galactica-character-game"
SERVICE_NAME="default"

# Activate venv so python3 resolves to the project's Python 3.12
# (system python3 may be 3.14+ which lacks project dependencies)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/venv_galactica/bin" ]; then
    export PATH="$SCRIPT_DIR/venv_galactica/bin:$PATH"
fi

# Check if a commit message was provided
if [ -z "$1" ]; then
  echo "You must provide a commit message."
  exit 1
fi

# =============================================================================
# SMOKE TESTS - Must pass before deployment
# =============================================================================
echo ""
echo "=== RUNNING QUICK SMOKE TESTS ==="
echo "Critical tests must pass before deploying to production..."
echo ""

# Run quick smoke tests (Tier 1 only, ~20 tests, ~5 seconds)
python3 -m tools.smoke_test local --quick
SMOKE_EXIT_CODE=$?

if [ $SMOKE_EXIT_CODE -ne 0 ]; then
  echo ""
  echo "❌ SMOKE TESTS FAILED - Deployment BLOCKED"
  echo ""
  echo "Fix the failing tests before deploying."
  echo "Run 'python -m tools.smoke_test local --verbose' for detailed errors."
  echo "Run 'python -m tools.smoke_test local --full' for comprehensive testing."
  echo ""
  exit 1
fi

echo ""
echo "✅ Quick smoke tests passed - proceeding with deployment"
echo ""

# Initialize the git repository if not already done
if [ ! -d ".git" ]; then
  echo "Setting up git repository for the first time..."

  git init
  if [ ! -f "README.md" ]; then
    echo "# Pilgrims - Mars Colony Game" >> README.md
    git add README.md
    git commit -m "Add README.md for initial setup"
  fi

  git remote add origin https://github.com/tillo13/pilgri.ms.git
  git branch -M main
  git push -u origin main
fi

# Add all changes to git
git add .

# Commit the changes with the provided message
git commit -m "$1"

# Push to GitHub
git push origin main

if [ $? -ne 0 ]; then
  echo ""
  echo "####################################"
  echo "# MERGE CONFLICT RESOLUTION STEPS: #"
  echo "####################################"
  echo ""
  echo "1. Fetch the latest changes from the remote repository:"
  echo "   git fetch origin"
  echo ""
  echo "2. Merge the changes from the remote branch into your local branch:"
  echo "   git merge origin/main"
  echo ""
  echo "3. If you encounter merge conflicts, open the conflicting files and resolve all conflicts manually."
  echo ""
  echo "4. Once resolved, stage the resolved files:"
  echo "   git add <filename>"
  echo ""
  echo "5. Finalize the merge with a commit:"
  echo "   git commit -m 'Resolve merge conflicts'"
  echo ""
  echo "6. Now push your changes again:"
  echo "   git push origin main"
  echo ""
  exit 1
fi

# CRITICAL SAFEGUARD: Verify we're deploying to the correct Google Cloud project
CURRENT_PROJECT=$(gcloud config get-value project)
echo ""
echo "=== GOOGLE CLOUD PROJECT VERIFICATION ==="
echo "Expected project: $EXPECTED_PROJECT"
echo "Current project:  $CURRENT_PROJECT"

if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
  echo ""
  echo "❌ ERROR: Google Cloud project mismatch!"
  echo "Current project '$CURRENT_PROJECT' does not match expected project '$EXPECTED_PROJECT'"
  echo ""
  echo "Attempting to switch to correct project..."
  
  # Try to use an existing configuration first
  if gcloud config configurations list --format="value(name)" | grep -q "galactica-config"; then
    echo "Using existing galactica-config configuration"
    gcloud config configurations activate galactica-config
  fi
  
  # CRITICAL FIX: ALWAYS set the project regardless of configuration
  echo "Setting project to $EXPECTED_PROJECT"
  gcloud config set project $EXPECTED_PROJECT
  
  # Brief pause to let the configuration take effect
  sleep 2
  
  # Verify the switch was successful
  CURRENT_PROJECT=$(gcloud config get-value project)
  if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
    echo ""
    echo "❌ CRITICAL ERROR: Failed to switch to $EXPECTED_PROJECT project!"
    echo "Deployment ABORTED to prevent deploying to wrong project."
    echo ""
    echo "Please manually set the project with one of these commands:"
    echo "  gcloud config configurations activate galactica-config"
    echo "  gcloud config set project $EXPECTED_PROJECT"
    echo ""
    echo "Then re-run this script."
    exit 1
  else
    echo "✅ Successfully switched to $EXPECTED_PROJECT project"
  fi
else
  echo "✅ Project verification passed - deploying to correct project"
fi

echo "=========================================="
echo ""

# Deploy to Google App Engine using the gcloud_deploy.py script
echo "Starting deployment to Google App Engine for $EXPECTED_PROJECT..."
python3 gcloud_deploy.py
DEPLOY_EXIT_CODE=$?

# Only proceed if deployment was successful
if [ $DEPLOY_EXIT_CODE -eq 0 ]; then
  echo ""
  echo "✅ Deployment to Google Cloud completed successfully!"
  echo ""

  # =============================================================================
  # POST-DEPLOY SPEED CHECK - Hit live pages, flag slow responses
  # =============================================================================
  echo "=== POST-DEPLOY SPEED CHECK (https://pilgri.ms) ==="
  echo "Waiting 15s for new instances to warm up..."
  sleep 15

  SPEED_THRESHOLD=5  # seconds - flag anything slower
  SPEED_FAIL=0
  PAGES="/ /crew /colony /depot /expeditions /research"

  for PAGE in $PAGES; do
    RESULT=$(curl -s -o /dev/null -w "%{http_code} %{time_total}" "https://pilgri.ms${PAGE}" --max-time 30 2>/dev/null)
    HTTP_CODE=$(echo $RESULT | awk '{print $1}')
    LOAD_TIME=$(echo $RESULT | awk '{print $2}')

    # Format output with status indicator
    if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "302" ]; then
      printf "  %-15s → HTTP %s in %ss  ❌ ERROR\n" "$PAGE" "$HTTP_CODE" "$LOAD_TIME"
      SPEED_FAIL=1
    elif [ "$(echo "$LOAD_TIME > $SPEED_THRESHOLD" | bc -l 2>/dev/null)" = "1" ]; then
      printf "  %-15s → HTTP %s in %ss  ⚠️  SLOW (>%ss)\n" "$PAGE" "$HTTP_CODE" "$LOAD_TIME" "$SPEED_THRESHOLD"
      SPEED_FAIL=1
    else
      printf "  %-15s → HTTP %s in %ss  ✅\n" "$PAGE" "$HTTP_CODE" "$LOAD_TIME"
    fi
  done

  echo ""
  if [ $SPEED_FAIL -eq 1 ]; then
    echo "⚠️  Some pages are slow or erroring — check above!"
  else
    echo "✅ All pages responding under ${SPEED_THRESHOLD}s"
  fi
  echo ""

  echo "📊 Tailing logs (Ctrl+C to stop)..."
  echo ""
  # Loop to restart log tailing if it disconnects
  while true; do
    gcloud app logs tail --service $SERVICE_NAME --project $EXPECTED_PROJECT
    echo ""
    echo "⚠️  Log stream disconnected. Reconnecting in 2 seconds... (Ctrl+C to stop)"
    sleep 2
  done
else
  echo ""
  echo "❌ Deployment failed with exit code: $DEPLOY_EXIT_CODE"
  echo "Please check the error messages above."
  exit $DEPLOY_EXIT_CODE
fi