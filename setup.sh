#!/usr/bin/env bash
set -e

echo "=== ReviewMe Setup ==="
echo ""

# --- Prerequisites ---
errors=0

printf "Checking Python... "
if command -v python3 &>/dev/null; then
    echo "OK ($(python3 --version 2>&1 | cut -d' ' -f2))"
else
    echo "MISSING - Install Python 3.13+"
    errors=1
fi

printf "Checking uv... "
if command -v uv &>/dev/null; then
    echo "OK"
else
    echo "MISSING"
    read -p "Install uv now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        errors=1
    fi
fi

printf "Checking claude CLI... "
if command -v claude &>/dev/null; then
    echo "OK"
else
    echo "MISSING"
    read -p "Install claude CLI now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        npm install -g @anthropic-ai/claude-code
    else
        errors=1
    fi
fi

if [ $errors -ne 0 ]; then
    echo ""
    echo "Fix the issues above and re-run ./setup.sh"
    exit 1
fi

echo ""
echo "--- Configuration ---"
echo ""

# --- .env setup ---
if [ -f .env ]; then
    read -p ".env already exists. Overwrite? (y/n) " -n 1 -r
    echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && skip_env=1
fi

if [ -z "$skip_env" ]; then
    echo "Tip: Create a classic PAT at https://github.com/settings/tokens"
    echo "     Scope needed: repo"
    read -p "GitHub PAT: " gh_token

    echo ""
    echo "Example: facebook/react, my-org/my-app"
    read -p "GitHub repo (owner/repo): " gh_repo

    echo ""
    echo "Example: /Users/john/dev/my-app (absolute path to your local clone)"
    read -p "Path to local clone: " repo_path

    echo ""
    echo "Example: review-me, needs-review, claude-review"
    read -p "Label to watch [review-me]: " review_label
    review_label=${review_label:-review-me}

    echo ""
    echo "The Claude Code agent used for reviews."
    echo "Example: pr-tech-lead-reviewer (must exist in .claude/agents/)"
    echo ""
    echo "  1. In Claude Code:  /plugin marketplace add joey-barbier/ClaudeCode-Plugin"
    read -p "Claude agent name [pr-tech-lead-reviewer]: " claude_agent
    claude_agent=${claude_agent:-pr-tech-lead-reviewer}

    echo ""
    echo "Safety limit per review. A typical review costs ~$0.10-0.50"
    read -p "Max budget per review in USD [1.00]: " max_budget
    max_budget=${max_budget:-1.00}

    echo ""
    echo "How often to check for new PRs. 300 = every 5 min"
    read -p "Poll interval in seconds [300]: " poll_interval
    poll_interval=${poll_interval:-300}

    cat > .env <<EOF
GITHUB_TOKEN=${gh_token}
GITHUB_REPO=${gh_repo}
REPO_PATH=${repo_path}
REVIEW_LABEL=${review_label}
CLAUDE_AGENT=${claude_agent}
MAX_BUDGET_USD=${max_budget}
POLL_INTERVAL=${poll_interval}
EOF

    echo ""
    echo ".env created"
fi

# --- Install deps ---
echo ""
echo "Installing dependencies..."
uv sync

# --- Test connection ---
echo ""
printf "Testing GitHub API access... "
status=$(uv run python -c "
from src.config import load_config
from src.github_client import GitHubClient
cfg = load_config()
gh = GitHubClient(cfg)
r = gh.check_rate_limit()
print(f'OK ({r[\"core\"][\"remaining\"]}/{r[\"core\"][\"limit\"]} requests)')
gh.close()
" 2>&1) && echo "$status" || echo "FAILED - check your token and repo"

echo ""
echo "=== Setup complete ==="
echo ""
echo "  Start the bot:       uv run reviewme"
echo "  Dashboard:           http://127.0.0.1:8420"
echo ""
