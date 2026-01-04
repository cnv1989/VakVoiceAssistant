# Setting Up Secrets in AWS Secrets Manager

This guide explains how to store and use the Deepgram API key and Twilio auth token in AWS Secrets Manager for secure credential management.

## Overview

The Vak application supports loading secrets from AWS Secrets Manager:
- **Deepgram API Key**: Required for Deepgram Voice Agent API
- **Twilio Auth Token**: Required for Twilio signature verification

## Quick Setup

### Option 1: Use the Setup Script (Recommended)

```bash
cd VakInfra
./create-secrets.sh
```

The script will prompt you for:
1. Deepgram API key
2. Twilio auth token (optional)

It will create/update the secrets and display the ARNs you need for deployment.

### Option 2: Manual Setup via AWS CLI

#### Create Deepgram API Key Secret

```bash
aws secretsmanager create-secret \
  --name vak/deepgram-api-key \
  --secret-string "your-deepgram-api-key-here" \
  --region us-west-2 \
  --description "Deepgram API key for Vak Voice Assistant"
```

#### Create Twilio Auth Token Secret

```bash
aws secretsmanager create-secret \
  --name vak/twilio-auth-token \
  --secret-string "your-twilio-auth-token-here" \
  --region us-west-2 \
  --description "Twilio auth token for signature verification"
```

#### Get Secret ARNs

After creating the secrets, get their ARNs:

```bash
# Deepgram secret ARN
aws secretsmanager describe-secret \
  --secret-id vak/deepgram-api-key \
  --region us-west-2 \
  --query 'ARN' \
  --output text

# Twilio secret ARN
aws secretsmanager describe-secret \
  --secret-id vak/twilio-auth-token \
  --region us-west-2 \
  --query 'ARN' \
  --output text
```

### Option 3: Manual Setup via AWS Console

1. Go to [AWS Secrets Manager Console](https://console.aws.amazon.com/secretsmanager/)
2. Click **"Store a new secret"**
3. Select **"Other type of secret"**
4. Choose **"Plaintext"** tab
5. Enter your secret value:
   - For Deepgram: `your-deepgram-api-key`
   - For Twilio: `your-twilio-auth-token`
6. Click **"Next"**
7. Secret name:
   - Deepgram: `vak/deepgram-api-key`
   - Twilio: `vak/twilio-auth-token`
8. Click **"Next"** → **"Store"**
9. Copy the **Secret ARN** (you'll need this for deployment)

## Deploying with Secrets

Once you have the secret ARNs, deploy the stack:

### Using Environment Variables

```bash
export DEEPGRAM_API_KEY_SECRET_ARN=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/deepgram-api-key-xxxxx
export TWILIO_AUTH_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/twilio-auth-token-xxxxx
export CERTIFICATE_ARN=arn:aws:acm:us-west-2:123456789012:certificate/xxxxx

cdk deploy VakAppStack
```

### Using CDK Context

```bash
cdk deploy VakAppStack \
  -c deepgramApiKeySecretArn=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/deepgram-api-key-xxxxx \
  -c twilioAuthTokenSecretArn=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/twilio-auth-token-xxxxx \
  -c certificateArn=arn:aws:acm:us-west-2:123456789012:certificate/xxxxx
```

### Using Both Secrets (Recommended)

```bash
DEEPGRAM_API_KEY_SECRET_ARN=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/deepgram-api-key-xxxxx \
TWILIO_AUTH_TOKEN_SECRET_ARN=arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/twilio-auth-token-xxxxx \
CERTIFICATE_ARN=arn:aws:acm:us-west-2:123456789012:certificate/xxxxx \
cdk deploy VakAppStack
```

## Updating Secrets

To update a secret value:

### Via AWS CLI

```bash
# Update Deepgram API key
aws secretsmanager update-secret \
  --secret-id vak/deepgram-api-key \
  --secret-string "new-api-key" \
  --region us-west-2

# Update Twilio auth token
aws secretsmanager update-secret \
  --secret-id vak/twilio-auth-token \
  --secret-string "new-auth-token" \
  --region us-west-2
```

After updating, force a new ECS deployment to pick up the new secret:

```bash
aws ecs update-service \
  --cluster vak-cluster \
  --service VakAppStack-VakService087430DF-8fNpTRvwuDhe \
  --force-new-deployment \
  --region us-west-2
```

### Via AWS Console

1. Go to Secrets Manager
2. Select the secret
3. Click **"Retrieve secret value"** → **"Edit"**
4. Update the value
5. Click **"Save"**
6. Force new ECS deployment (see above)

## How It Works

1. **Secrets Storage**: Secrets are stored in AWS Secrets Manager as plain strings
2. **IAM Permissions**: The ECS task execution role is granted read permissions to the secrets
3. **Environment Variables**: ECS injects the secret values as environment variables:
   - `DEEPGRAM_API_KEY` - from `vak/deepgram-api-key` secret
   - `TWILIO_AUTH_TOKEN` - from `vak/twilio-auth-token` secret
4. **Application**: The application reads these environment variables via `config.py`

## Security Benefits

- ✅ **No hardcoded credentials** in code or configuration files
- ✅ **Encrypted at rest** by AWS Secrets Manager
- ✅ **Encrypted in transit** when retrieved by ECS
- ✅ **Audit trail** - all secret access is logged in CloudTrail
- ✅ **Rotation support** - can enable automatic rotation if needed
- ✅ **Access control** - IAM policies control who can read secrets

## Troubleshooting

### Secret Not Found

```
Error: Secrets Manager can't find the specified secret
```

**Solution**: Verify the secret exists and the ARN is correct:
```bash
aws secretsmanager describe-secret --secret-id vak/deepgram-api-key --region us-west-2
```

### Permission Denied

```
Error: User is not authorized to perform: secretsmanager:GetSecretValue
```

**Solution**: Ensure the ECS task execution role has permission:
- The CDK stack automatically grants read permissions
- Verify the role has `secretsmanager:GetSecretValue` permission

### Environment Variable Not Set

If the application can't find the secret:
1. Check ECS task definition - verify secrets are configured
2. Check CloudWatch logs - look for errors about missing environment variables
3. Verify the secret ARN is correct in the stack

### Verify Secrets in ECS Task

```bash
# Get running task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster vak-cluster \
  --service-name VakAppStack-VakService087430DF-8fNpTRvwuDhe \
  --region us-west-2 \
  --query 'taskArns[0]' \
  --output text)

# Check task definition (shows secret references)
aws ecs describe-tasks \
  --cluster vak-cluster \
  --tasks $TASK_ARN \
  --region us-west-2 \
  --query 'tasks[0].containers[0].secrets'
```

## Optional: Secret Rotation

For production, consider enabling automatic secret rotation:

```bash
# Enable rotation for Deepgram API key (requires Lambda function)
aws secretsmanager rotate-secret \
  --secret-id vak/deepgram-api-key \
  --rotation-lambda-arn arn:aws:lambda:us-west-2:123456789012:function:rotate-secret \
  --region us-west-2
```

Note: You'll need to create a Lambda function to handle the rotation logic.

## References

- [AWS Secrets Manager Documentation](https://docs.aws.amazon.com/secretsmanager/)
- [ECS Secrets Integration](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data-secrets.html)
- [CDK Secrets Manager Construct](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_secretsmanager-readme.html)
