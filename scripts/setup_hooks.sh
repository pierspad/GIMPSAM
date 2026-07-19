#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/setup_hooks.sh — point git at the versioned hooks in
# scripts/git-hooks (core.hooksPath is per-clone config, so every clone
# opts in explicitly with this one command).
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x scripts/git-hooks/*
git config core.hooksPath scripts/git-hooks
echo "git hooks enabled: $(git config core.hooksPath)"
