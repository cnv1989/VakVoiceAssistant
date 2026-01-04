# Vak Infrastructure

CDK v2 infrastructure for the Vak Voice Assistant stack.

## Prerequisites

- Node.js 20+
- AWS CLI configured
- AWS CDK CLI installed: `npm install -g aws-cdk`

## Setup

1. Install dependencies:
```bash
npm install
```

2. Bootstrap CDK (if not already done):
```bash
# Your AWS Account ID: 844341423871
cdk bootstrap aws://844341423871/us-west-2

# Or let CDK auto-detect from your AWS credentials:
cdk bootstrap
```

3. Build the TypeScript code:
```bash
npm run build
```

4. Synthesize CloudFormation template:
```bash
npm run synth
```

5. Deploy the stack:
```bash
npm run deploy
```

## Stack Components

- **VPC**: 2 Availability Zones with public and private subnets
- **ECS Fargate**: Deepgram Voice Agent service on port 8080
- **Application Load Balancer**: Public-facing ALB with HTTP/HTTPS listeners
- **WAF**: Web Application Firewall for API key authentication (optional)
- **SSM Parameter Store**: Stores API key securely (if WAF enabled)
- **DynamoDB**: Sessions table with TTL
- **S3**: Artifacts bucket for transcripts and audio
- **ECR**: Repository for Docker images
- **IAM**: Roles with minimal permissions (Deepgram uses external API)

## Secure WebSocket (WSS) Setup

To enable secure WebSocket connections (WSS), you need to provide an ACM certificate ARN:

### Creating an ACM Certificate

#### Option 1: AWS Console (Recommended for first-time setup)

1. **Navigate to Certificate Manager**:
   - Go to [AWS Certificate Manager Console](https://console.aws.amazon.com/acm/home)
   - Make sure you're in the **us-west-2** region (same as your stack)
   - Click **"Request a certificate"**

2. **Request a public certificate**:
   - Select **"Request a public certificate"**
   - Click **"Next"**

3. **Enter domain names**:
   - **Fully qualified domain name**: Enter your domain (e.g., `example.com`)
   - **Subject alternative names (SANs)**: Optional - add `*.example.com` for wildcard or additional domains
   - Click **"Request"**

4. **Choose validation method**:
   - **DNS validation** (Recommended):
     - ACM provides CNAME records to add to your DNS
     - More secure and doesn't require email access
     - Copy the CNAME name and value
     - Add them to your DNS provider (Route 53, Cloudflare, etc.)
   - **Email validation**:
     - ACM sends validation emails to domain admin addresses
     - Click the link in the email to validate

5. **Wait for validation**:
   - Status changes from "Pending validation" to "Issued" (usually 5-30 minutes)
   - You'll receive an email when validation is complete

6. **Get the Certificate ARN**:
   - Click on your certificate in the ACM console
   - Copy the **Certificate ARN** (format: `arn:aws:acm:us-west-2:844341423871:certificate/xxxx-xxxx-xxxx-xxxx`)

#### Option 2: AWS CLI

```bash
# Request a certificate
aws acm request-certificate \
  --domain-name example.com \
  --subject-alternative-names "*.example.com" \
  --validation-method DNS \
  --region us-west-2

# This returns the Certificate ARN immediately
# Example output:
# {
#   "CertificateArn": "arn:aws:acm:us-west-2:844341423871:certificate/12345678-1234-1234-1234-123456789012"
# }

# Get validation records (for DNS validation)
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID \
  --region us-west-2 \
  --query 'Certificate.DomainValidationOptions[*].[DomainName,ResourceRecord.Name,ResourceRecord.Value]' \
  --output table

# Check certificate status
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID \
  --region us-west-2 \
  --query 'Certificate.Status' \
  --output text
```

#### Option 3: CDK (Automated - requires Route 53 hosted zone)

If you have a Route 53 hosted zone, you can create the certificate via CDK:

```typescript
// Add to vak-app-stack.ts or create a separate certificate stack
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as route53targets from 'aws-cdk-lib/aws-route53-targets';

const hostedZone = route53.HostedZone.fromLookup(this, 'HostedZone', {
  domainName: 'example.com',
});

const certificate = new certificatemanager.Certificate(this, 'VakCertificate', {
  domainName: 'example.com',
  subjectAlternativeNames: ['*.example.com'],
  validation: certificatemanager.CertificateValidation.fromDns(hostedZone),
});
```

### Deploying with Certificate

Once you have the certificate ARN:

```bash
# Option 1: Using environment variable (RECOMMENDED)
CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID cdk deploy

# Option 2: Using CDK context
cdk deploy -c certificateArn=arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID

# Option 3: Export and use
export CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID
cdk deploy
```

**Important Notes**:
- Certificate must be in the **same region** as your ALB (us-west-2)
- Certificate must be **validated** (status: "Issued") before use
- For ALB, you can use a certificate for a different domain than the ALB DNS name
- If using ALB DNS name directly, you'll need a certificate for that specific domain or use a wildcard

3. **What happens when certificate is provided**:
   - HTTPS listener created on port 443 with TLS 1.2/1.3
   - HTTP listener on port 80 redirects to HTTPS
   - WebSocket connections use `wss://` protocol
   - All traffic is encrypted end-to-end

4. **Without certificate**:
   - Only HTTP listener on port 80 (no encryption)
   - WebSocket connections use `ws://` protocol
   - Suitable for development/testing only

## WAF API Key Authentication

To protect your ALB with static API key authentication using AWS WAF:

1. **Deploy with API Key**:
   ```bash
   # Option 1: Using environment variable (RECOMMENDED)
   API_KEY=your-secret-api-key-here cdk deploy
   
   # Option 2: Using CDK context (not recommended - stores key in cdk.context.json)
   cdk deploy -c apiKey=your-secret-api-key-here
   ```

2. **How it works**:
   - WAF WebACL is attached to the ALB
   - All requests must include `X-API-Key` header with the correct value
   - Health checks (`/health`) are allowed without API key
   - Requests without valid API key are blocked (403 Forbidden)
   - API key is stored in SSM Parameter Store at `/vak/api-key`

3. **Using the API key in clients**:
   ```javascript
   // WebSocket connection with API key
   const ws = new WebSocket('wss://your-alb-dns/ws', {
     headers: {
       'X-API-Key': 'your-secret-api-key-here'
     }
   });
   ```

   ```bash
   # HTTP request with API key
   curl -H "X-API-Key: your-secret-api-key-here" https://your-alb-dns/ws
   ```

4. **Updating the API key**:
   ```bash
   # Update via AWS CLI
   aws ssm put-parameter \
     --name /vak/api-key \
     --value "new-api-key" \
     --type SecureString \
     --overwrite \
     --region us-west-2
   
   # Note: WAF rule needs to be updated separately via CDK or Console
   ```

5. **Security considerations**:
   - Use a strong, randomly generated API key (minimum 32 characters recommended)
   - Rotate the API key periodically
   - Never commit API keys to version control
   - Consider using AWS Secrets Manager for more advanced key management
   - Monitor WAF metrics in CloudWatch for blocked requests

6. **Combining with WSS**:
   ```bash
   # Deploy with both certificate and API key
   CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID \
   API_KEY=your-secret-api-key-here \
   cdk deploy
   ```

## Outputs

After deployment, the stack outputs:
- `WebSocketUrl`: WebSocket endpoint URL (WSS if certificate provided, WS otherwise)
- `WebSocketSecureUrl`: Secure WebSocket endpoint URL (WSS) - only if certificate provided
- `WebSocketInsecureUrl`: Insecure WebSocket endpoint URL (WS) - only if certificate provided
- `AlbDns`: Application Load Balancer DNS name
- `AlbArn`: Application Load Balancer ARN (for IAM policies)
- `WebAclArn`: WAF WebACL ARN - only if API key provided
- `ApiKeyParameterName`: SSM Parameter Store name for API key - only if API key provided
- `DynamoDbTableName`: DynamoDB Sessions table name
- `S3BucketName`: S3 Artifacts bucket name

## Environment Variables

The ECS task receives these environment variables:
- `REGION`: AWS region (us-west-2)
- `BUCKET`: S3 artifacts bucket name
- `DDB_TABLE`: DynamoDB sessions table name
- `MODEL_ID`: Bedrock model ID (default: anthropic.claude-3-haiku-20240307-v1:0)
- `POLLY_VOICE`: Polly voice ID (default: Joanna)

Note: `WS_API_ENDPOINT` must be set manually after deployment. It follows the pattern:
`https://{api-id}.execute-api.{region}.amazonaws.com/prod`
