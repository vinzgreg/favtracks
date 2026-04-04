#!/bin/bash
set -euo pipefail

echo "FavTracks starting..."

# Run incremental computation on startup to pick up new activities
echo "Running incremental segment computation..."
python3 -m favtracks incremental

echo "Starting web server..."
exec python3 -m favtracks serve
