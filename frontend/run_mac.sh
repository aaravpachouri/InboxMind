#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 20+ with npm is required. Install from https://nodejs.org/"
  exit 1
fi
if [[ ! -f .env.local ]]; then cp .env.example .env.local; fi
if [[ ! -f node_modules/vite/bin/vite.js ]]; then
  echo "Installing dashboard dependencies..."
  npm install
fi
npm run dev
