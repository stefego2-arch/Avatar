#!/usr/bin/env bash
# push_all.sh — trimite commiturile curente la ambele remote-uri simultan
# Folosire: bash push_all.sh [mesaj commit opțional]
#           bash push_all.sh          → push fără commit nou
#           bash push_all.sh "mesaj"  → git add -A + commit + push

set -e

BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Dacă s-a dat un mesaj, facem commit automat
if [ -n "$1" ]; then
    git add -A
    git commit -m "$1" || echo "Nimic nou de commitat."
fi

echo "→ Push pe Codeberg (origin)..."
git push origin "$BRANCH" &
PID1=$!

echo "→ Push pe GitHub (github)..."
git push github "$BRANCH" &
PID2=$!

# Așteptăm ambele push-uri
wait $PID1 && echo "✅ Codeberg OK" || echo "❌ Codeberg FAIL"
wait $PID2 && echo "✅ GitHub OK"   || echo "❌ GitHub FAIL"
