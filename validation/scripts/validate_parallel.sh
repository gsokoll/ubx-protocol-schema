#!/bin/bash
# Run multiple validation processes in parallel at shell level
# Each process handles a subset of messages

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Number of parallel processes
NUM_PROCS=${1:-8}

# Get remaining messages
REMAINING=$(uv run python -c "
import json
from pathlib import Path

# Load all messages
with open('data/messages/ubx_messages.json') as f:
    data = json.load(f)
all_msgs = sorted([m['name'] for m in data.get('messages', [])])

# Load validated
status_file = Path('validation/reports/message_status.json')
if status_file.exists():
    with open(status_file) as f:
        status = json.load(f)
    validated = set(status.get('messages', {}).keys())
else:
    validated = set()

# Print remaining
remaining = [m for m in all_msgs if m not in validated]
for m in remaining:
    print(m)
")

# Count remaining
TOTAL=$(echo "$REMAINING" | wc -l)
echo "Remaining messages: $TOTAL"
echo "Running $NUM_PROCS parallel processes"
echo ""

# Split into chunks and run in parallel
echo "$REMAINING" | xargs -P "$NUM_PROCS" -I {} bash -c '
    msg="$1"
    result=$(uv run python validation/scripts/validate_message.py "$msg" --no-save 2>&1)
    
    # Extract summary
    if echo "$result" | grep -q "Matches:"; then
        matches=$(echo "$result" | grep "Matches:" | awk "{print \$2}")
        mismatches=$(echo "$result" | grep "Mismatches:" | awk "{print \$2}")
        if [ "$mismatches" = "0" ]; then
            echo "✓ $msg (matches: $matches)"
        else
            echo "⚠ $msg (mismatches: $mismatches)"
        fi
    else
        echo "? $msg"
    fi
' _ {}

echo ""
echo "=== Complete ==="
uv run python validation/scripts/validate_all_messages.py --status
