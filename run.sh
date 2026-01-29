#!/bin/bash

# Exit on error
set -e

# Default values
MAX_RESULTS=100
ISSUES_RESULTS=15
FORCE_UPDATE=false
SOURCE="arxiv"  # valid values: arxiv, crossref, acm, openalex, semanticscholar, ieee, all
LOG_FILE="ai_agriculture_news.log"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --max-results)
            MAX_RESULTS="$2"
            shift 2
            ;;
        --issues-results)
            ISSUES_RESULTS="$2"
            shift 2
            ;;
        --force-update)
            FORCE_UPDATE=true
            shift
            ;;
        --source)
            SOURCE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Starting AI Agriculture News Update Script..."
echo "Selected source: $SOURCE"

# Determine flags for main.py based on additional sources
INCLUDE_FLAGS=""

case "$SOURCE" in
    arxiv)
        INCLUDE_FLAGS=""
        ;;
    crossref)
        INCLUDE_FLAGS="--include-crossref"
        ;;
    acm)
        INCLUDE_FLAGS="--include-acm"
        ;;
    openalex)
        INCLUDE_FLAGS="--include-openalex"
        ;;
    semanticscholar)
        INCLUDE_FLAGS="--include-semanticscholar"
        ;;
    ieee)
        INCLUDE_FLAGS="--include-ieee"
        ;;
    all)
        INCLUDE_FLAGS="--include-crossref --include-acm --include-openalex --include-semanticscholar --include-ieee"
        ;;
    *)
        echo "Invalid source: $SOURCE. Valid options are: arxiv, crossref, acm, openalex, semanticscholar, ieee, all."
        exit 1
        ;;
esac

# Create log directory if it doesn't exist
mkdir -p logs

# Execute the main script with arguments
echo "Running main.py..."
python3 main.py \
    --max-results "$MAX_RESULTS" \
    --issues-results "$ISSUES_RESULTS" \
    ${FORCE_UPDATE:+--force-update} \
    $INCLUDE_FLAGS

# Check if the script executed successfully
if [ $? -eq 0 ]; then
    echo "Script completed successfully!"
    # Archive the log file with timestamp
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    mv "$LOG_FILE" "logs/${TIMESTAMP}_${LOG_FILE}"
else
    echo "Script failed with error code $?"
    exit 1
fi 