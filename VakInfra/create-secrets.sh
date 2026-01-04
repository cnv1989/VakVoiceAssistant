#!/bin/bash
# Script to create secrets in AWS Secrets Manager for Vak application
# Usage: ./create-secrets.sh

set -e

REGION="us-west-2"

echo "Creating secrets in AWS Secrets Manager (region: $REGION)"
echo ""

# Deepgram API Key Secret
echo "Creating Deepgram API key secret..."
read -sp "Enter your Deepgram API key: " DEEPGRAM_API_KEY
echo ""
if [ -z "$DEEPGRAM_API_KEY" ]; then
    echo "Error: Deepgram API key cannot be empty"
    exit 1
fi

DEEPGRAM_SECRET_ARN=$(aws secretsmanager create-secret \
    --name vak/deepgram-api-key \
    --secret-string "$DEEPGRAM_API_KEY" \
    --region $REGION \
    --description "Deepgram API key for Vak Voice Assistant" \
    --query 'ARN' \
    --output text 2>/dev/null || \
    aws secretsmanager update-secret \
    --secret-id vak/deepgram-api-key \
    --secret-string "$DEEPGRAM_API_KEY" \
    --region $REGION \
    --query 'ARN' \
    --output text)

echo "✓ Deepgram secret created/updated: $DEEPGRAM_SECRET_ARN"
echo ""

# Twilio Auth Token Secret
echo "Creating Twilio auth token secret..."
read -sp "Enter your Twilio auth token: " TWILIO_AUTH_TOKEN
echo ""
if [ -z "$TWILIO_AUTH_TOKEN" ]; then
    echo "Warning: Twilio auth token is empty. Signature verification will be skipped."
    TWILIO_AUTH_TOKEN=""
fi

if [ -n "$TWILIO_AUTH_TOKEN" ]; then
    TWILIO_SECRET_ARN=$(aws secretsmanager create-secret \
        --name vak/twilio-auth-token \
        --secret-string "$TWILIO_AUTH_TOKEN" \
        --region $REGION \
        --description "Twilio auth token for signature verification" \
        --query 'ARN' \
        --output text 2>/dev/null || \
        aws secretsmanager update-secret \
        --secret-id vak/twilio-auth-token \
        --secret-string "$TWILIO_AUTH_TOKEN" \
        --region $REGION \
        --query 'ARN' \
        --output text)
    
    echo "✓ Twilio secret created/updated: $TWILIO_SECRET_ARN"
else
    echo "⚠ Twilio secret not created (empty token)"
    TWILIO_SECRET_ARN=""
fi

echo ""
echo "=========================================="
echo "Secrets created successfully!"
echo "=========================================="
echo ""
echo "Use these ARNs when deploying:"
echo ""
echo "  DEEPGRAM_API_KEY_SECRET_ARN=$DEEPGRAM_SECRET_ARN \\"
if [ -n "$TWILIO_SECRET_ARN" ]; then
    echo "  TWILIO_AUTH_TOKEN_SECRET_ARN=$TWILIO_SECRET_ARN \\"
fi
echo "  CERTIFICATE_ARN=your-certificate-arn \\"
echo "  cdk deploy VakAppStack"
echo ""
echo "Or set them as environment variables:"
echo ""
echo "  export DEEPGRAM_API_KEY_SECRET_ARN=$DEEPGRAM_SECRET_ARN"
if [ -n "$TWILIO_SECRET_ARN" ]; then
    echo "  export TWILIO_AUTH_TOKEN_SECRET_ARN=$TWILIO_SECRET_ARN"
fi
echo "  export CERTIFICATE_ARN=your-certificate-arn"
echo "  cdk deploy VakAppStack"
echo ""
