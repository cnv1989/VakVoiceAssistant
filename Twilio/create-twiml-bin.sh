#!/bin/bash

# Script to create TwiML Bin via Twilio API
# Requires: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables

set -e

TWILIO_ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-}"
TWILIO_AUTH_TOKEN="${TWILIO_AUTH_TOKEN:-}"
TWIML_BIN_NAME="${TWIML_BIN_NAME:-Vak Voice Assistant}"
TWIML_FILE="${1:-twiml-bin.xml}"

if [ -z "$TWILIO_ACCOUNT_SID" ] || [ -z "$TWILIO_AUTH_TOKEN" ]; then
    echo "Error: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set"
    echo "Usage: TWILIO_ACCOUNT_SID=xxx TWILIO_AUTH_TOKEN=xxx ./create-twiml-bin.sh [twiml-file.xml]"
    exit 1
fi

if [ ! -f "$TWIML_FILE" ]; then
    echo "Error: TwiML file not found: $TWIML_FILE"
    exit 1
fi

echo "Creating TwiML Bin: $TWIML_BIN_NAME"
echo "Using file: $TWIML_FILE"
echo ""

# Read TwiML content
TWIML_CONTENT=$(cat "$TWIML_FILE")

# Create TwiML Bin via API
RESPONSE=$(curl -s -X POST "https://runtime.twilio.com/v1/TwimlBins" \
    -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN" \
    -d "FriendlyName=$TWIML_BIN_NAME" \
    -d "Twiml=$TWIML_CONTENT")

# Extract TwiML Bin SID and URL
BIN_SID=$(echo "$RESPONSE" | grep -o '"sid":"[^"]*"' | cut -d'"' -f4)
BIN_URL=$(echo "$RESPONSE" | grep -o '"url":"[^"]*"' | cut -d'"' -f4)

if [ -z "$BIN_SID" ]; then
    echo "Error: Failed to create TwiML Bin"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "✅ TwiML Bin created successfully!"
echo ""
echo "Bin SID: $BIN_SID"
echo "Bin URL: $BIN_URL"
echo ""
echo "Use this URL in your Twilio phone number configuration:"
echo "  $BIN_URL"
