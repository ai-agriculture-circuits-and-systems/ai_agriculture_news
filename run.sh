#!/bin/bash

# Exit on error
set -e

# Default values
MAX_RESULTS=100
ISSUES_RESULTS=15
FORCE_UPDATE=false
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
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Starting AI Agriculture News Update Script..."

# Create log directory if it doesn't exist
mkdir -p logs

# Execute the main script with arguments
echo "Running main.py..."
python3 main.py \
    --max-results "$MAX_RESULTS" \
    --issues-results "$ISSUES_RESULTS" \
    ${FORCE_UPDATE:+--force-update}

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