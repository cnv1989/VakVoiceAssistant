# Debugging WSS Connection Issues

## Current Status

✅ **Working:**
- WebSocket upgrade handshake: `HTTP/1.1 101 Switching Protocols`
- ALB HTTP/2: Disabled
- Certificate: Valid for `vak.tutzi.ai`
- DNS: Correctly configured
- Target Health: Healthy
- Backend Service: Running and responding

## Testing Steps

### 1. Test WebSocket Connection

Open browser console and run:
```javascript
const ws = new WebSocket('wss://vak.tutzi.ai/ws');
ws.onopen = () => console.log('✅ Connected!');
ws.onerror = (e) => console.error('❌ Error:', e);
ws.onclose = (e) => console.log('🔌 Closed:', e.code, e.reason);
ws.onmessage = (e) => console.log('📨 Message:', e.data);

// Send a test message after connection
setTimeout(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({action: 'start-recording'}));
  }
}, 1000);
```

### 2. Check Browser Console

Look for:
- Connection errors
- Close codes (1006, 1002, 1008, etc.)
- Network errors
- CORS errors

### 3. Common Issues

#### Issue: Connection closes immediately (1006)
**Possible causes:**
- Backend service crashing
- Protocol mismatch
- Message format issue

**Check:**
- ECS task logs
- Backend service health
- Message format matches server expectations

#### Issue: Protocol error (1002)
**Possible causes:**
- HTTP/2 still enabled (should be disabled)
- ALB configuration issue

**Check:**
```bash
aws elbv2 describe-load-balancer-attributes \
  --load-balancer-arn "ALB_ARN" \
  --query 'Attributes[?Key==`routing.http2.enabled`]'
```

#### Issue: Policy violation (1008)
**Possible causes:**
- Server rejecting connection
- Authentication issue
- Invalid message format

**Check:**
- Backend logs
- Server-side error messages

### 4. Verify Backend is Receiving Connections

Check ECS logs:
```bash
# Find log group
aws logs describe-log-groups --query 'logGroups[?contains(logGroupName, `vak`) || contains(logGroupName, `deepgram`)].logGroupName'

# Tail logs
aws logs tail /aws/ecs/vak-deepgram --follow --region us-west-2
```

### 5. Test Direct Connection

If you have access to the container IP:
```bash
# Get task IP
TASK_IP=$(aws ecs describe-tasks --cluster vak-cluster --tasks TASK_ARN --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' --output text)

# Test direct connection (if accessible)
curl -v --http1.1 -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: test" -H "Sec-WebSocket-Version: 13" \
  http://$TASK_IP:8080/ws
```

## Expected Behavior

1. **Connection**: WebSocket should upgrade successfully (101 Switching Protocols)
2. **Initial Message**: Server may send welcome message or wait for client action
3. **Client Action**: Send `{action: 'start-recording'}` to begin
4. **Server Response**: Should receive `{type: 'recording-started'}` or similar

## Debugging Checklist

- [ ] WebSocket upgrade returns 101 Switching Protocols
- [ ] Connection stays open (doesn't close immediately)
- [ ] Can send messages from client
- [ ] Can receive messages from server
- [ ] No CORS errors in browser console
- [ ] No network errors
- [ ] Backend logs show connection established
- [ ] Backend logs show messages received

## Next Steps

1. **Check browser console** for specific error messages
2. **Check ECS logs** for backend errors
3. **Test with test-websocket.html** file
4. **Verify message format** matches server expectations
5. **Check if connection closes immediately** or stays open
