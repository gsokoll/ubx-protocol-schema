#!/bin/bash
# Run Gemini extraction on all PDF manuals
# Usage: ./scripts/run_gemini_extraction_all.sh [--parallel N]

source ~/.bashrc

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Parse arguments
PARALLEL_JOBS=1
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel|-p)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Function to process a single PDF
process_pdf() {
    local PDF="$1"
    local BASENAME=$(basename "$PDF" .pdf)
    # Use full PDF stem for output filename (matching updated Python script)
    local OUTPUT_FILE="data/ubx/by-manual/${BASENAME}_gemini.json"
    
    if [ -f "$OUTPUT_FILE" ]; then
        echo "[SKIP] $(basename "$PDF")"
        return 0
    fi
    
    echo "[START] $(basename "$PDF")"
    if ~/.local/bin/uv run python scripts/extract_messages_with_gemini.py \
        --pdf-path "$PDF" \
        --all-messages 2>&1; then
        echo "[DONE] $(basename "$PDF")"
    else
        echo "[FAILED] $(basename "$PDF")"
        return 1
    fi
}

export -f process_pdf

# Find only Interface Description PDFs (exclude PCN, firmware notices, etc.)
PDFS=$(find interface_manuals -name "*.pdf" | grep -E "InterfaceDescription|Interfacedescription|ReceiverDescrProtSpec" | sort)
TOTAL=$(echo "$PDFS" | wc -l)

echo "=== Gemini UBX Message Extraction ==="
echo "Found $TOTAL PDFs to process"
echo "Parallel jobs: $PARALLEL_JOBS"
echo "Started at: $(date)"
echo ""

if [ "$PARALLEL_JOBS" -gt 1 ]; then
    # Parallel execution using GNU parallel or xargs
    if command -v parallel &> /dev/null; then
        echo "$PDFS" | parallel -j "$PARALLEL_JOBS" process_pdf {}
    else
        echo "$PDFS" | xargs -P "$PARALLEL_JOBS" -I {} bash -c 'process_pdf "$@"' _ {}
    fi
else
    # Sequential execution
    for PDF in $PDFS; do
        process_pdf "$PDF"
    done
fi

echo ""
echo "=== Summary ==="
echo "Completed at: $(date)"
echo "Output files: $(ls data/ubx/by-manual/*gemini*.json 2>/dev/null | wc -l)"
