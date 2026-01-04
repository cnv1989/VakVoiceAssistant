# Setting Up Deepgram API Key Secret

The WebSocket connection is failing because the `DEEPGRAM_API_KEY` is not configured in the ECS task. This causes the connection to close immediately (error 1006) when trying to start a Deepgram session.

## Create the Secret

### Option 1: AWS CLI

```bash
# Create the secret
aws secretsmanager create-secret \
  --name vak/deepgram-api-key \
  --secret-string "your-deepgram-api-key-here" \
  --region us-west-2 \
  --description "Deepgram API key for Vak Voice Assistant"

# Get the secret ARN (you'll need this for deployment)
aws secretsmanager describe-secret \
  --secret-id vak/deepgram-api-key \
  --region us-west-2 \
  --query 'ARN' \
  --output text
```

### Option 2: AWS Console

1. Go to [AWS Secrets Manager Console](https://console.aws.amazon.com/secretsmanager/)
2. Click **"Store a new secret"**
3. Select **"Other type of secret"**
4. Enter:
   - **Secret key/value**: `DEEPGRAM_API_KEY` / `your-api-key-here`
5. Click **"Next"**
6. Secret name: `vak/deepgram-api-key`
7. Click **"Store"**
8. Copy the **Secret ARN** (you'll need this)

## Deploy with Secret

Once you have the secret ARN, deploy the stack:

```bash
cd VakInfra

# Get your secret ARN
SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id vak/deepgram-api-key \
  --region us-west-2 \
  --query 'ARN' \
  --output text)

# Deploy with certificate and Deepgram API key
CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2 \
DEEPGRAM_API_KEY_SECRET_ARN=$SECRET_ARN \
cdk deploy VakAppStack --require-approval never
```

## Verify

After deployment, the ECS task will have access to the Deepgram API key, and WebSocket connections should work properly.

## Troubleshooting

If the connection still fails:

1. **Verify secret exists**:
   ```bash
   aws secretsmanager describe-secret --secret-id vak/deepgram-api-key --region us-west-2
   ```

2. **Check task definition**:
   ```bash
   aws ecs describe-task-definition \
     --task-definition VakAppStackVakTaskDefinition8E28D363 \
     --query 'taskDefinition.containerDefinitions[0].secrets' \
     --output json
   ```

3. **Check ECS task logs** for errors:
   ```bash
   # Find log group
   aws logs describe-log-groups --query 'logGroups[?contains(logGroupName, `vak`)].logGroupName'
   
   # Tail logs
   aws logs tail /aws/ecs/vak-deepgram --follow --region us-west-2
   ```
