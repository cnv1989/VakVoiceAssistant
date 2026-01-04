# WAF Changes Summary

## What Was Added

### 1. AWS WAF v2 IP Set
- **Name**: `vak-twilio-ips-VakAppStack`
- **Purpose**: Stores Twilio IP address ranges
- **Scope**: REGIONAL (required for ALB)
- **IP Version**: IPv4
- **IP Ranges**: ~40 Twilio IP ranges configured

### 2. AWS WAF v2 WebACL
- **Name**: `vak-twilio-only-VakAppStack`
- **Purpose**: Restrict ALB access to Twilio IPs only
- **Scope**: REGIONAL
- **Default Action**: **BLOCK** (all traffic blocked by default)
- **Rules**:
  - **Priority 1**: `AllowTwilioIPs` - ALLOW traffic from Twilio IP Set

### 3. WebACL Association
- **Associated Resource**: ALB (`VakApp-VakAl-S9TUK4zMiO73`)
- **Status**: Active

## Configuration Details

### Default Action
```json
{
  "block": {}
}
```
- **Effect**: All traffic is blocked by default
- **Reason**: Security-first approach - only explicitly allowed IPs can access

### Allow Rule
```json
{
  "name": "AllowTwilioIPs",
  "priority": 1,
  "action": {
    "allow": {}
  },
  "statement": {
    "ipSetReferenceStatement": {
      "arn": "<TwilioIpSet ARN>"
    }
  }
}
```
- **Effect**: Traffic from Twilio IP ranges is allowed
- **Priority**: 1 (evaluated first)

## Current Behavior

### ✅ Allowed Traffic
- **Twilio Media Streams**: ✅ Allowed (from Twilio IPs)
- **Twilio WebSocket connections**: ✅ Allowed (from Twilio IPs)

### ❌ Blocked Traffic
- **Browser connections**: ❌ Blocked (not from Twilio IPs)
- **Direct API calls**: ❌ Blocked (not from Twilio IPs)
- **Any non-Twilio traffic**: ❌ Blocked

## Impact

### Before WAF
- ✅ Twilio calls worked
- ✅ Browser access worked
- ❌ No IP-based protection
- ❌ Anyone could access the ALB

### After WAF (Current)
- ✅ Twilio calls work
- ❌ Browser access blocked
- ✅ Only Twilio IPs can access
- ✅ ALB protected from unauthorized access

## Twilio IP Ranges Configured

The following IP ranges are currently allowed:

**Primary Ranges:**
- `54.172.60.0/22`
- `54.244.51.0/24`
- `54.171.127.192/26`
- `54.173.34.0/24`
- `54.235.223.0/24`

**Extended Ranges:**
- `54.236.1.0/24` through `54.236.31.0/24` (31 subnets)

**Total**: ~40 IP ranges

## Monitoring

### CloudWatch Metrics

**WebACL Metrics:**
- `AllowedRequests` - Requests allowed by Twilio IP rule
- `BlockedRequests` - Requests blocked (non-Twilio IPs)
- `CountedRequests` - Total requests evaluated

**Rule Metrics:**
- `AllowTwilioIPs` - Requests matching Twilio IP rule

### View Metrics

```bash
# View blocked requests
aws cloudwatch get-metric-statistics \
  --namespace AWS/WAFV2 \
  --metric-name BlockedRequests \
  --dimensions Name=WebACL,Value=vak-twilio-only-VakAppStack \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum \
  --region us-west-2
```

## How to Disable WAF

If you need to allow browser access again:

```bash
cd VakInfra
CERTIFICATE_ARN=arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2 \
ENABLE_TWILIO_ONLY_ACCESS=false \
cdk deploy VakAppStack
```

This will:
- Remove WebACL association from ALB
- Keep WebACL and IP Set (can be reused later)
- Allow all traffic to ALB

## How to Update Twilio IPs

### Via AWS Console
1. Go to **WAF & Shield** → **IP sets**
2. Find: `vak-twilio-ips-VakAppStack`
3. Click **Edit**
4. Update IP addresses
5. Save

### Via CDK
1. Update `twilioIpRanges` array in `lib/vak-app-stack.ts`
2. Redeploy: `cdk deploy VakAppStack`

### Via AWS CLI
```bash
# Get IP Set ID
IP_SET_ID=$(aws wafv2 list-ip-sets --scope REGIONAL --region us-west-2 \
  --query "IPSets[?Name=='vak-twilio-ips-VakAppStack'].Id" --output text)

# Get Lock Token
LOCK_TOKEN=$(aws wafv2 get-ip-set \
  --scope REGIONAL \
  --id $IP_SET_ID \
  --region us-west-2 \
  --query 'LockToken' --output text)

# Update IP Set
aws wafv2 update-ip-set \
  --scope REGIONAL \
  --id $IP_SET_ID \
  --name vak-twilio-ips-VakAppStack \
  --addresses "54.172.60.0/22" "54.244.51.0/24" \
  --lock-token $LOCK_TOKEN \
  --region us-west-2
```

## Resources Created

1. **IP Set**: `vak-twilio-ips-VakAppStack`
   - ARN: `arn:aws:wafv2:us-west-2:844341423871:regional/ipset/vak-twilio-ips-VakAppStack/...`

2. **WebACL**: `vak-twilio-only-VakAppStack`
   - ARN: `arn:aws:wafv2:us-west-2:844341423871:regional/webacl/vak-twilio-only-VakAppStack/...`

3. **WebACL Association**: Links WebACL to ALB

## Cost Impact

- **WAF**: ~$1/month per WebACL + $0.60 per million requests
- **IP Set**: Free
- **Minimal cost** for typical Twilio call volume

## Security Benefits

1. ✅ **IP-based protection** - Only Twilio can access
2. ✅ **DDoS protection** - WAF provides basic DDoS mitigation
3. ✅ **Traffic filtering** - Blocks unauthorized access attempts
4. ✅ **Monitoring** - CloudWatch metrics for security monitoring

## Limitations

1. ⚠️ **Browser access blocked** - `/ws` endpoint not accessible from browsers
2. ⚠️ **IP changes** - Twilio IPs may change, need periodic updates
3. ⚠️ **No path-based rules** - Applies to entire ALB (both `/ws` and `/twilio`)

## Future Enhancements

To allow both Twilio and browser access:
1. Use path-based WAF rules (allow all for `/ws`, Twilio-only for `/twilio`)
2. Or use separate ALBs (one public, one Twilio-only)
3. Or implement application-level authentication
