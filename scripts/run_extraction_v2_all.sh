#!/bin/bash
# Run v2 extraction workflow on all PDF manuals
# Usage: ./scripts/run_extraction_v2_all.sh [--parallel N] [--stage 1|2|3|4]
#
# Stages:
#   1 - Initial extraction (parallel across PDFs)
#   2 - Voting (single process, fast)
#   3 - Self-review (parallel across PDFs)
#   4 - Final determination (single process, fast)
#   (no stage specified = run all)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Parse arguments
PARALLEL_JOBS=1
STAGE=""
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel|-p)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --stage|-s)
            STAGE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Directories
CONV_DIR="_working/stage1_extractions"
PRELIM_DIR="data/preliminary"
OUTPUT_DIR="data/final"
REPORTS_DIR="analysis_reports/v2"

# Find only Interface Description PDFs
PDFS=$(find interface_manuals -name "*.pdf" | grep -E "InterfaceDescription|Interfacedescription|ReceiverDescrProtSpec" | sort)
TOTAL=$(echo "$PDFS" | wc -l)

echo "=== Workflow v2: Multi-shot Extraction with Self-Review ==="
echo "Found $TOTAL PDFs"
echo "Parallel jobs: $PARALLEL_JOBS"
echo "Stage: ${STAGE:-all}"
echo "Started at: $(date)"
echo ""

# Stage 1: Initial Extraction
run_stage_1() {
    echo "=== STAGE 1: Initial Extraction (Gemini 2.5 Flash) ==="
    
    process_extraction() {
        local PDF="$1"
        local BASENAME=$(basename "$PDF" .pdf)
        echo "[START] $BASENAME"
        uv run python scripts/extract_messages_v2.py extract \
            --pdf-path "$PDF" \
            --all-messages \
            --conv-dir "$CONV_DIR" \
            $DRY_RUN 2>&1
        echo "[DONE] $BASENAME"
    }
    export -f process_extraction
    export CONV_DIR DRY_RUN
    
    if [ "$PARALLEL_JOBS" -gt 1 ]; then
        if command -v parallel &> /dev/null; then
            echo "$PDFS" | parallel -j "$PARALLEL_JOBS" process_extraction {}
        else
            echo "$PDFS" | xargs -P "$PARALLEL_JOBS" -I {} bash -c 'process_extraction "$@"' _ {}
        fi
    else
        for PDF in $PDFS; do
            process_extraction "$PDF"
        done
    fi
    
    echo "Stage 1 complete."
}

# Stage 2: Voting
run_stage_2() {
    echo ""
    echo "=== STAGE 2: Preliminary Voting ==="
    uv run python scripts/vote_preliminary_v2.py \
        --conv-dir "$CONV_DIR" \
        --output-dir "$PRELIM_DIR" \
        --verbose $DRY_RUN
    echo "Stage 2 complete."
}

# Stage 3: Self-Review (reviews each message/version ONCE, not per-manual)
run_stage_3() {
    echo ""
    echo "=== STAGE 3: Self-Review (Gemini 3 Flash) ==="
    echo "Reviewing each unique message/version once..."
    
    uv run python scripts/extract_messages_v2.py review-all \
        --conv-dir "$CONV_DIR" \
        --preliminary-dir "$PRELIM_DIR" \
        --parallel "$PARALLEL_JOBS" \
        $DRY_RUN
    
    echo "Stage 3 complete."
}

# Stage 4: Final Determination
run_stage_4() {
    echo ""
    echo "=== STAGE 4: Final Automated Determination ==="
    uv run python scripts/final_determination_v2.py \
        --conv-dir "$CONV_DIR" \
        --output-dir "$OUTPUT_DIR" \
        --reports-dir "$REPORTS_DIR" \
        --verbose $DRY_RUN
    echo "Stage 4 complete."
}

# Run stages based on argument
case "$STAGE" in
    1)
        run_stage_1
        ;;
    2)
        run_stage_2
        ;;
    3)
        run_stage_3
        ;;
    4)
        run_stage_4
        ;;
    *)
        # Run all stages
        run_stage_1
        run_stage_2
        run_stage_3
        run_stage_4
        ;;
esac

echo ""
echo "=== Summary ==="
echo "Completed at: $(date)"
echo "Conversations: $(find "$CONV_DIR" -name "*.json" 2>/dev/null | wc -l) files"
echo "Preliminary:   $(find "$PRELIM_DIR" -name "*.json" 2>/dev/null | wc -l) files"
echo "Canonical:     $(find "$OUTPUT_DIR/canonical" -name "*.json" 2>/dev/null | wc -l) files"

# Check for manual adjudication
if [ -f "$REPORTS_DIR/manual_adjudication_required.json" ]; then
    echo ""
    echo "⚠️  Manual adjudication may be required. See: $REPORTS_DIR/manual_adjudication_required.json"
fi
