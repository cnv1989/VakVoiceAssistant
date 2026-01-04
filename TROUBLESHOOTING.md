# Troubleshooting WSS Connection Issues

## Issue: WebSocket Connection Failing

### Symptoms
- WebSocket connections to `wss://vak.tutzi.ai/ws` fail
- Connection times out or returns error codes
- Browser shows WebSocket connection errors

### Root Causes and Solutions

#### 1. HTTP/2 Enabled on ALB
**Problem**: ALB had HTTP/2 enabled, which doesn't support WebSocket upgrades (WebSocket requires HTTP/1.1)

**Solution**: Disabled HTTP/2 on ALB
- Set `routing.http2.enabled` to `false`
- Increased idle timeout to 3600 seconds (1 hour) for long-lived WebSocket connections

**Status**: ✅ Fixed in infrastructure code

#### 2. ALB Idle Timeout Too Short
**Problem**: Default ALB idle timeout (60 seconds) may disconnect long WebSocket sessions

**Solution**: Increased to 3600 seconds (1 hour)
- Configured via ALB attribute `idle_timeout.timeout_seconds`

**Status**: ✅ Fixed in infrastructure code

#### 3. Target Health Check
**Problem**: Target group health checks failing

**Check**:
```bash
TG_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "ALB_ARN" --query 'Listeners[?Port==`443`].DefaultActions[0].TargetGroupArn' --output text)
aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --query 'TargetHealthDescriptions[*].[Target.Id,TargetHealth.State]' --output table
```

**Solution**: Ensure ECS tasks are running and healthy

#### 4. Certificate Issues
**Problem**: SSL/TLS certificate not valid for domain

**Check**:
```bash
openssl s_client -connect vak.tutzi.ai:443 -servername vak.tutzi.ai < /dev/null 2>&1 | grep -E "(Verify return code|CN=)"
```

**Solution**: Ensure certificate covers `vak.tutzi.ai` (wildcard `*.tutzi.ai` works)

**Status**: ✅ Certificate is valid

#### 5. DNS Resolution
**Problem**: DNS not pointing to ALB

**Check**:
```bash
dig +short vak.tutzi.ai
# Should return ALB IPs: 54.191.146.199, 54.213.138.27
```

**Status**: ✅ DNS is correctly configured

### Testing WebSocket Connection

#### Using curl (HTTP/1.1 required)
```bash
curl -v --http1.1 --no-buffer \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
  -H "Sec-WebSocket-Version: 13" \
  https://vak.tutzi.ai/ws
```

Expected: HTTP/1.1 101 Switching Protocols

#### Using Browser Console
```javascript
const ws = new WebSocket('wss://vak.tutzi.ai/ws');
ws.onopen = () => console.log('Connected');
ws.onerror = (e) => console.error('Error:', e);
ws.onclose = (e) => console.log('Closed:', e.code, e.reason);
```

#### Using wscat (if installed)
```bash
wscat -c wss://vak.tutzi.ai/ws
```

### Current Configuration

- **ALB DNS**: `VakApp-VakAl-S9TUK4zMiO73-829936755.us-west-2.elb.amazonaws.com`
- **Custom Domain**: `vak.tutzi.ai` → ALB
- **Certificate**: `tutzi.ai` and `*.tutzi.ai` (valid)
- **HTTP/2**: Disabled (required for WebSocket)
- **Idle Timeout**: 3600 seconds (1 hour)
- **Target Health**: Healthy
- **WebSocket Endpoint**: `/ws` on port 8080

### Debugging Steps

1. **Check ALB attributes**:
   ```bash
   aws elbv2 describe-load-balancer-attributes --load-balancer-arn "ALB_ARN" --query 'Attributes'
   ```

2. **Check listener configuration**:
   ```bash
   aws elbv2 describe-listeners --load-balancer-arn "ALB_ARN" --query 'Listeners[*].[Port,Protocol]'
   ```

3. **Check target health**:
   ```bash
   aws elbv2 describe-target-health --target-group-arn "TG_ARN"
   ```

4. **Check ECS service**:
   ```bash
   aws ecs describe-services --cluster vak-cluster --services VakAppStack-VakService087430DF-8fNpTRvwuDhe
   ```

5. **Check container logs**:
   ```bash
   aws logs tail /aws/ecs/vak-deepgram --follow
   ```

### Common Error Codes

- **1006**: Abnormal closure - often indicates connection rejected or timeout
- **1002**: Protocol error - check HTTP/2 is disabled
- **1008**: Policy violation - check security groups and WAF rules
- **1011**: Server error - check backend service logs

### Next Steps if Still Failing

1. Verify HTTP/2 is disabled: `routing.http2.enabled = false`
2. Check security groups allow traffic on port 443
3. Verify target group health checks are passing
4. Check ECS task logs for errors
5. Test direct connection to container IP (if accessible)
6. Verify WebSocket endpoint exists at `/ws` on backend
