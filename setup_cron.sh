#!/bin/bash
# ──────────────────────────────────────────────
# Setup daily cron job for Apartment Hunter
# Runs every morning at 7:00 AM local time
# ──────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH="$(which python3)"
CRON_SCHEDULE="0 7 * * *"  # 7:00 AM daily. Change as needed.

# Build the cron command
CRON_CMD="$CRON_SCHEDULE cd $SCRIPT_DIR && $PYTHON_PATH main.py >> $SCRIPT_DIR/output/cron.log 2>&1"

echo "📅 Setting up daily apartment search..."
echo ""
echo "  Schedule:  Every day at 7:00 AM"
echo "  Script:    $SCRIPT_DIR/main.py"
echo "  Log:       $SCRIPT_DIR/output/cron.log"
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "apartment-hunter"; then
    echo "⚠️  Existing apartment-hunter cron job found. Replacing..."
    crontab -l | grep -v "apartment-hunter" | crontab -
fi

# Add the cron job with a comment marker
(crontab -l 2>/dev/null; echo "# apartment-hunter daily search"; echo "$CRON_CMD") | crontab -

echo "✅ Cron job installed!"
echo ""
echo "To verify:  crontab -l"
echo "To remove:  crontab -l | grep -v apartment-hunter | crontab -"
echo ""
echo "💡 Make sure your API keys are set in your shell profile:"
echo "   echo 'export RENTCAST_API_KEY=your-key' >> ~/.bashrc"
echo "   echo 'export RAPIDAPI_KEY=your-key' >> ~/.bashrc"
