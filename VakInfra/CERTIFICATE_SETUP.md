# ACM Certificate Setup Guide

This guide provides detailed instructions for creating and managing AWS Certificate Manager (ACM) certificates for use with the Vak ALB.

## Prerequisites

- AWS account with appropriate permissions
- Domain name (or subdomain) you want to secure
- Access to DNS provider (Route 53, Cloudflare, etc.) for DNS validation

## Quick Start: AWS Console Method

### Step 1: Request Certificate

1. Open [AWS Certificate Manager Console](https://console.aws.amazon.com/acm/home)
2. **Important**: Select region **us-west-2** (must match your ALB region)
3. Click **"Request a certificate"**
4. Select **"Request a public certificate"**
5. Click **"Next"**

### Step 2: Enter Domain Information

- **Domain name**: Enter your domain (e.g., `api.example.com` or `example.com`)
- **Subject alternative names (SANs)**: Optional
  - Add `*.example.com` for wildcard certificate
  - Or add specific subdomains: `api.example.com`, `ws.example.com`
- Click **"Request"**

### Step 3: Validate Domain

#### DNS Validation (Recommended)

1. ACM will show **CNAME records** to add to your DNS
2. Copy the **Name** and **Value** for each domain
3. Add these records to your DNS provider:
   - **Route 53**: Go to Hosted Zones → Your domain → Create record
   - **Cloudflare**: DNS → Add record → CNAME
   - **Other providers**: Add CNAME record with the provided values
4. Wait 5-30 minutes for DNS propagation
5. ACM will automatically validate when DNS records are found

#### Email Validation (Alternative)

1. ACM sends emails to these addresses:
   - `admin@example.com`
   - `administrator@example.com`
   - `hostmaster@example.com`
   - `postmaster@example.com`
   - `webmaster@example.com`
2. Click the validation link in the email
3. Certificate will be issued immediately after clicking

### Step 4: Get Certificate ARN

1. Once status changes to **"Issued"**, click on the certificate
2. Copy the **Certificate ARN**:
   ```
   arn:aws:acm:us-west-2:844341423871:certificate/12345678-1234-1234-1234-123456789012
   ```

## AWS CLI Method

### Request Certificate

```bash
# Request certificate for a single domain
aws acm request-certificate \
  --domain-name api.example.com \
  --validation-method DNS \
  --region us-west-2

# Request certificate with wildcard
aws acm request-certificate \
  --domain-name example.com \
  --subject-alternative-names "*.example.com" \
  --validation-method DNS \
  --region us-west-2
```

**Output**:
```json
{
  "CertificateArn": "arn:aws:acm:us-west-2:844341423871:certificate/12345678-1234-1234-1234-123456789012"
}
```

### Get DNS Validation Records

```bash
CERT_ARN="arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID"

# Get validation records
aws acm describe-certificate \
  --certificate-arn $CERT_ARN \
  --region us-west-2 \
  --query 'Certificate.DomainValidationOptions[*].[DomainName,ResourceRecord.Name,ResourceRecord.Value]' \
  --output table
```

**Example Output**:
```
------------------------------------------
|  DescribeCertificate                   |
+------------------+---------------------+
|  example.com     |  _abc123.example.com|  _abc123.def456.acm-validations.aws. |
|  *.example.com   |  _xyz789.example.com|  _xyz789.uvw012.acm-validations.aws. |
+------------------+---------------------+
```

Add these CNAME records to your DNS provider.

### Check Certificate Status

```bash
aws acm describe-certificate \
  --certificate-arn $CERT_ARN \
  --region us-west-2 \
  --query 'Certificate.Status' \
  --output text
```

Status values:
- `PENDING_VALIDATION`: Waiting for DNS/email validation
- `ISSUED`: Certificate is ready to use ✅
- `VALIDATION_TIMED_OUT`: Validation failed (need to re-request)
- `FAILED`: Certificate request failed

### List All Certificates

```bash
aws acm list-certificates \
  --region us-west-2 \
  --query 'CertificateSummaryList[*].[CertificateArn,DomainName,Status]' \
  --output table
```

## Using ALB DNS Name Directly

If you want to use the ALB DNS name directly (e.g., `vak-alb-123456789.us-west-2.elb.amazonaws.com`):

### Option 1: Use a Custom Domain (Recommended)

1. Create a certificate for your custom domain (e.g., `api.yourdomain.com`)
2. Point a CNAME record to your ALB DNS name:
   ```
   api.yourdomain.com → vak-alb-123456789.us-west-2.elb.amazonaws.com
   ```
3. Use the custom domain in your WebSocket connections

### Option 2: Request Certificate for ALB DNS (Not Recommended)

1. Deploy stack first to get ALB DNS name
2. Request certificate for the ALB DNS domain (e.g., `vak-alb-123456789.us-west-2.elb.amazonaws.com`)
3. **Problem**: ALB DNS names are not valid domains for certificates
4. **Solution**: Use a custom domain instead

## Common Issues and Solutions

### Issue: Certificate Status Stuck on "Pending Validation"

**Solution**:
- Verify DNS records are correctly added
- Check DNS propagation: `dig _abc123.example.com CNAME`
- Ensure CNAME name and value match exactly (case-sensitive)
- Wait up to 30 minutes for DNS propagation

### Issue: "Certificate not found" Error

**Solution**:
- Verify certificate is in **us-west-2** region
- Check certificate ARN format is correct
- Ensure certificate status is **"Issued"**

### Issue: Certificate Expired

**Solution**:
- ACM certificates auto-renew, but you can manually request a new one
- Update the certificate ARN in your deployment

### Issue: Wrong Region

**Solution**:
- ALB and certificate must be in the same region
- Your stack uses **us-west-2**
- If certificate is in wrong region, request a new one in us-west-2

## Testing Certificate

After deploying with certificate:

```bash
# Test HTTPS endpoint
curl -v https://your-alb-dns/health

# Test WebSocket (should use wss://)
# Check browser console or WebSocket client
```

## Certificate ARN Format

```
arn:aws:acm:{region}:{account-id}:certificate/{certificate-id}
```

Example:
```
arn:aws:acm:us-west-2:844341423871:certificate/12345678-1234-1234-1234-123456789012
```

## Next Steps

Once you have the certificate ARN:

1. **Deploy with certificate**:
   ```bash
   CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/YOUR-CERT-ID cdk deploy
   ```

2. **Verify WSS is working**:
   - Check stack outputs for `WebSocketSecureUrl`
   - Test WebSocket connection with `wss://` protocol

3. **Optional: Add API key protection**:
   ```bash
   CERTIFICATE_ARN=... API_KEY=your-secret-key cdk deploy
   ```

## Additional Resources

- [AWS Certificate Manager Documentation](https://docs.aws.amazon.com/acm/)
- [ACM Best Practices](https://docs.aws.amazon.com/acm/latest/userguide/acm-bestpractices.html)
- [DNS Validation Guide](https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html)
