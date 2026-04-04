#!/bin/bash
set -euo pipefail

echo "FavTracks starting..."

# Run incremental computation on startup to pick up new activities
echo "Running incremental segment computation..."
python3 /app/__main__.py incremental

echo "Starting web server..."
exec python3 /app/__main__.py serve
