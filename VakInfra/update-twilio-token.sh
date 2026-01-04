#!/bin/bash
# Script to update Twilio auth token in AWS Secrets Manager
# Usage: ./update-twilio-token.sh [new-token]

set -e

REGION="us-west-2"
SECRET_NAME="vak/twilio-auth-token"

if [ -z "$1" ]; then
    echo "Usage: $0 <new-twilio-auth-token>"
    echo ""
    echo "Current token:"
    aws secretsmanager get-secret-value \
        --secret-id $SECRET_NAME \
        --region $REGION \
        --query 'SecretString' \
        --output text
    echo ""
    echo "To update, run: $0 'your-new-token-here'"
    exit 1
fi

NEW_TOKEN="$1"

echo "Updating Twilio auth token in Secrets Manager..."
echo "Secret: $SECRET_NAME"
echo ""

aws secretsmanager update-secret \
    --secret-id $SECRET_NAME \
    --secret-string "$NEW_TOKEN" \
    --region $REGION \
    --query 'ARN' \
    --output text

echo ""
echo "✓ Token updated successfully!"
echo ""
echo "To apply the change to running ECS tasks, force a new deployment:"
echo ""
echo "  aws ecs update-service \\"
echo "    --cluster vak-cluster \\"
echo "    --service VakAppStack-VakService087430DF-8fNpTRvwuDhe \\"
echo "    --force-new-deployment \\"
echo "    --region us-west-2"
echo ""
