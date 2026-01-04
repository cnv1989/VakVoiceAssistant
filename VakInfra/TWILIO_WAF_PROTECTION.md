# Protecting ALB for Twilio Calls Only

This guide explains how to restrict ALB access to only Twilio IP addresses using AWS WAF.

## Overview

When `enableTwilioOnlyAccess` is enabled, AWS WAF is configured to:
- **Block** all traffic by default
- **Allow** only traffic from Twilio IP ranges
- Protect both `/ws` (browser) and `/twilio` endpoints

## Deployment

### Enable Twilio-Only Access

```bash
cd VakInfra
ENABLE_TWILIO_ONLY_ACCESS=true CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2 cdk deploy VakAppStack
```

Or using context:

```bash
cdk deploy VakAppStack -c enableTwilioOnlyAccess=true -c certificateArn=arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2
```

### Disable Twilio-Only Access (Allow All)

```bash
cdk deploy VakAppStack -c enableTwilioOnlyAccess=false -c certificateArn=arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2
```

## Important Considerations

### ⚠️ Browser Access Will Be Blocked

When `enableTwilioOnlyAccess=true`:
- ✅ Twilio calls will work
- ❌ Browser access to `/ws` will be **BLOCKED** (not from Twilio IPs)

### Solution: Path-Based Rules (Advanced)

If you need both Twilio and browser access:
1. Keep `enableTwilioOnlyAccess=false` (allow all)
2. Implement application-level authentication
3. Or use separate ALBs (one for Twilio, one for browsers)

## Updating Twilio IP Ranges

Twilio IP ranges change periodically. To update:

### Option 1: Update via AWS Console

1. Go to **AWS WAF Console** → **IP sets**
2. Find the IP set: `vak-twilio-ips-VakAppStack`
3. Click **Edit**
4. Get latest IPs from: https://www.twilio.com/docs/voice/ip-addresses
5. Update the IP ranges
6. Save

### Option 2: Update via CDK

1. Get latest Twilio IPs:
   ```bash
   curl https://www.twilio.com/docs/voice/ip-addresses
   ```

2. Update `twilioIpRanges` array in `lib/vak-app-stack.ts`

3. Redeploy:
   ```bash
   cdk deploy VakAppStack
   ```

### Option 3: Update via AWS CLI

```bash
# Get current IP set ID
IP_SET_ID=$(aws wafv2 list-ip-sets --scope REGIONAL --region us-west-2 \
  --query "IPSets[?Name=='vak-twilio-ips-VakAppStack'].Id" --output text)

# Get current IP set ARN
IP_SET_ARN=$(aws wafv2 get-ip-set --scope REGIONAL --id $IP_SET_ID --region us-west-2 \
  --query 'IPSet.ARN' --output text)

# Update with new IPs (replace with actual Twilio IPs)
aws wafv2 update-ip-set \
  --scope REGIONAL \
  --id $IP_SET_ID \
  --name vak-twilio-ips-VakAppStack \
  --addresses "54.172.60.0/22" "54.244.51.0/24" \
  --lock-token $(aws wafv2 get-ip-set --scope REGIONAL --id $IP_SET_ID --region us-west-2 --query 'LockToken' --output text) \
  --region us-west-2
```

## Current Twilio IP Ranges

The following IP ranges are configured (as of deployment):

- `54.172.60.0/22`
- `54.244.51.0/24`
- `54.171.127.192/26`
- `54.173.34.0/24`
- `54.235.223.0/24`
- `54.236.1.0/24` through `54.236.31.0/24`

**⚠️ Important**: These IPs may change. Check [Twilio IP Ranges](https://www.twilio.com/docs/voice/ip-addresses) periodically.

## Monitoring WAF

### View Blocked Requests

1. Go to **CloudWatch** → **Metrics** → **AWS/WAFV2**
2. Look for `BlockedRequests` metric
3. Filter by WebACL: `vak-twilio-only-VakAppStack`

### View Allowed Requests

1. CloudWatch → Metrics → AWS/WAFV2
2. Look for `AllowedRequests` metric
3. Filter by Rule: `AllowTwilioIPs`

### Check WAF Logs

Enable WAF logging to S3 or CloudWatch Logs to see detailed request information.

## Testing

### Test Twilio Connection

1. Call your Twilio phone number
2. Connection should work (from Twilio IP)
3. Check CloudWatch metrics for `AllowedRequests`

### Test Browser Access (Should Fail)

1. Try connecting from browser: `wss://vak.tutzi.ai/ws`
2. Connection should be blocked (not from Twilio IP)
3. Check CloudWatch metrics for `BlockedRequests`

## Troubleshooting

### Twilio Calls Not Working

**Check:**
- ✅ WAF WebACL is associated with ALB
- ✅ Twilio IPs are in the IP set
- ✅ IP set is up to date (check Twilio docs)
- ✅ CloudWatch metrics show `AllowedRequests`

**Fix:**
- Update IP set with latest Twilio IPs
- Check WAF logs for blocked requests

### Too Many Blocked Requests

If you see many blocked requests:
- Check if Twilio IPs have changed
- Verify IP set includes all Twilio regions you use
- Consider temporarily disabling WAF to test

## Alternative: Application-Level Protection

Instead of WAF IP allowlist, you can:

1. **Keep WAF disabled** (`enableTwilioOnlyAccess=false`)
2. **Validate Twilio requests** in application code:
   - Verify Twilio signature headers
   - Check request origin
   - Implement rate limiting

3. **Use API keys** (but browsers can't send headers in WebSocket)

## Resources

- [Twilio IP Ranges](https://www.twilio.com/docs/voice/ip-addresses)
- [AWS WAF Documentation](https://docs.aws.amazon.com/waf/)
- [WAF IP Sets](https://docs.aws.amazon.com/waf/latest/developerguide/waf-ip-set-managing.html)
