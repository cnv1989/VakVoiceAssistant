# FAQ / Troubleshooting

## Setup

**`./vak init` says a Deepgram API key is required — where do I get one?**
Sign up at [console.deepgram.com](https://console.deepgram.com); the free
tier is enough to try Vak.

**Do I need a Square or Setmore account to try Vak?**
No. `./vak init`'s "local test mode" runs a mock business (fake hours,
services, and staff) so you can hear the full flow before connecting a real
account. See [CONFIGURATION.md](./CONFIGURATION.md#connecting-a-real-square--setmore-account).

**`./vak dev` fails to create the Python virtual environment.**
Make sure `python3 -m venv` works standalone (`python3 -m venv /tmp/test-venv`).
On Debian/Ubuntu you may need `apt install python3-venv`.

**Do I need ElevenLabs credentials for the ElevenLabs voice option?**
No — Deepgram's Voice Agent API proxies ElevenLabs TTS directly. Your
Deepgram API key is all you need.

## Local development

**The mic button does nothing / no audio is captured.**
Browsers only allow microphone access on `https://` or `http://localhost`
origins. If you're testing over a network IP or a non-localhost hostname,
serve VakClient over HTTPS or use an SSH tunnel back to localhost.

**I get "WebSocket connection failed" locally.**
Confirm the backend is actually running (`curl http://localhost:8080/health`)
and that `VakClient/.env`'s `VITE_WS_URL` matches the port VakDeepGram is
listening on (default `8080`).

## Deployment

**WebSocket connections fail after deploying (works over `ws://` locally, not `wss://`).**
Common causes, roughly in order of likelihood:

1. **HTTP/2 enabled on the ALB.** WebSocket upgrades require HTTP/1.1.
   VakInfra's ALB already disables HTTP/2 (`routing.http2.enabled = false`)
   — if you're customizing the stack, don't re-enable it.
2. **ALB idle timeout too short.** Long-lived WebSocket sessions need a
   generous idle timeout; VakInfra sets 3600s. Check
   `aws elbv2 describe-load-balancer-attributes --load-balancer-arn <arn>`.
3. **Target group unhealthy.** `aws elbv2 describe-target-health --target-group-arn <arn>` —
   if targets are unhealthy, check ECS task logs
   (`aws logs tail /ecs/vak-service-production --follow`).
4. **Certificate doesn't cover your domain.** `openssl s_client -connect <your-domain>:443 -servername <your-domain> </dev/null 2>&1 | grep -E "Verify return code|CN="`.
5. **DNS not pointing at the ALB.** `dig +short <your-domain>` should
   resolve to the ALB's IPs.

**Common WebSocket close codes:**

| Code | Meaning |
|---|---|
| `1006` | Abnormal closure — often a rejected connection or network issue |
| `1002` | Protocol error — check that HTTP/2 is disabled on the ALB |
| `1008` | Policy violation — check security groups and WAF rules |
| `1011` | Server error — check backend logs |

**`cdk bootstrap` or `cdk deploy` fails with a permissions error.**
Your AWS credentials need permissions for CloudFormation, EC2, ECS, ECR,
DynamoDB, S3, IAM, and (if using WAF/Cognito/Route 53 options) those
services too. Administrator access is the simplest fix for a first deploy;
scope it down for production per your org's policies.

**`INVALID_SETTINGS - model not available` from Deepgram.**
The configured `DEEPGRAM_THINKING_MODEL` was deprecated or isn't enabled
for your account. Update `DEEPGRAM_THINKING_MODEL` in `.env` (or
`deepgram_thinking_model` in `VakDeepGram/src/vakdeepgram/config.py`) to a
current model and restart.

**ECS task stuck in `PENDING` or keeps restarting.**
```bash
aws ecs describe-tasks --cluster vak-cluster-production \
  --tasks $(aws ecs list-tasks --cluster vak-cluster-production --query 'taskArns[0]' --output text) \
  --query 'tasks[0].stoppedReason'
```
Common causes: missing secrets, ECR image pull failure, or the task running
out of memory.

## Something else?

Check [docs/ARCHITECTURE.md](./ARCHITECTURE.md) for how the pieces fit
together, or open an issue.
