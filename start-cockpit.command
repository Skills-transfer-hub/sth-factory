#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec /Users/hugo/.local/bin/python3.12 factory.py serve --runs-root /Users/hugo/Developer/sth/sth-factory-runs/local-validation --port 51240
