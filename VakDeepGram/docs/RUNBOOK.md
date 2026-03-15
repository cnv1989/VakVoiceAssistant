# VakDeepGram Operations Runbook

## Quick Reference

| Resource | Value |
|----------|-------|
| AWS Account | `844341423871`, region `us-west-2` |
| ECR Repo | `vak-deepgram` (tags: alpha / beta / prod) |
| ECS Clusters | `vak-cluster-alpha`, `vak-cluster-beta`, `vak-cluster-prod` |
| CloudWatch Log Groups | `/ecs/vak-service-{alpha\|beta\|prod}` |
| Prod API | `https://api.groommate.ai` |
| Beta API | `https://beta-api.groommate.ai` |
| Alpha API | `https://alpha-api.groommate.ai` |
| Twilio Account SID | `ACd00787e66384ec2d2ed3e262748525af` |
| Twilio Business Number | `+15104054454` |
| Twilio Toll-Free | `+18664766609` |

---

## 1. Check Service Health

```bash
# Prod
curl https://api.groommate.ai/

# Beta / Alpha
curl https://beta-api.groommate.ai/
curl https://alpha-api.groommate.ai/
```

Expected response:
```json
{"service":"VakDeepGram","version":"1.0.0","status":"running",...}
```

---

## 2. View Container Logs

```bash
# Tail live logs (last 30 min)
aws logs tail /ecs/vak-service-prod --since 30m --region us-west-2 --format short

# Filter for errors only
aws logs filter-log-events \
  --log-group-name /ecs/vak-service-prod \
  --start-time $(date -u -v-2H +%s000) \
  --filter-pattern "ERROR" \
  --region us-west-2 \
  --query 'events[*].message' \
  --output text

# Filter for a specific call session
aws logs filter-log-events \
  --log-group-name /ecs/vak-service-prod \
  --start-time $(date -u -v-1H +%s000) \
  --filter-pattern "twilio-XXXXX" \
  --region us-west-2 \
  --query 'events[*].message' \
  --output text
```

Replace `prod` with `alpha` or `beta` for other stages.

---

## 3. ECS Deployment

### Check deployment status
```bash
CLUSTER=vak-cluster-prod
SERVICE=$(aws ecs list-services --cluster $CLUSTER --query 'serviceArns[0]' --output text --region us-west-2)

aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
  --region us-west-2 \
  --query 'services[0].{status:status,running:runningCount,pending:pendingCount,deployments:deployments}'
```

### Force a new deployment (if GH Actions skipped ECS update)
```bash
aws ecs update-service \
  --cluster vak-cluster-prod \
  --service $(aws ecs list-services --cluster vak-cluster-prod --query 'serviceArns[0]' --output text --region us-west-2 | xargs basename) \
  --force-new-deployment \
  --region us-west-2

# Wait for stability
aws ecs wait services-stable --cluster vak-cluster-prod \
  --services $(aws ecs list-services --cluster vak-cluster-prod --query 'serviceArns[0]' --output text --region us-west-2 | xargs basename) \
  --region us-west-2
```

### Trigger a full redeploy via GitHub Actions
```bash
cd /Users/nag/Projects/voice_ai/vak
gh workflow run deploy-vakdeepgram.yml --ref prod --field stage=prod
```

---

## 4. Endpoint Smoke Tests

```bash
# Health
curl -s https://api.groommate.ai/health

# Twilio TwiML voice webhook (expects 403 without valid signature)
curl -s -o /dev/null -w "%{http_code}" -X POST https://api.groommate.ai/twilio/twiml
# Expected: 403

# Twilio SMS webhook (expects 400 without body)
curl -s -o /dev/null -w "%{http_code}" -X POST https://api.groommate.ai/twilio-chat
# Expected: 400

# Chat endpoint (expects 422 without API key)
curl -s -o /dev/null -w "%{http_code}" -X POST https://api.groommate.ai/chat
# Expected: 422
```

---

## 5. Common Errors and Fixes

### `INVALID_SETTINGS - model not available`
**Cause:** Deepgram Voice Agent rejected the configured thinking model (e.g. preview model was deprecated).
**Fix:** Update `deepgram_thinking_model` in `src/vakdeepgram/config.py` to a stable model (e.g. `gemini-2.0-flash` or `gpt-4o-mini`), commit, and push to main.

### `No active Deepgram session for twilio-XXXXX, ignoring audio`
**Cause:** Twilio keeps streaming audio briefly after a call ends. This is a benign race condition.
**Fix:** None needed — these warnings are expected during call teardown.

### `Invalid Twilio signature` / `Missing X-Twilio-Signature header`
**Cause:** Request to `/twilio/twiml` or `/twilio-chat` without a valid Twilio signature. Could be a health probe, a test curl, or a spoofed request.
**Fix:** Benign if infrequent. If excessive, check if Twilio webhook URL is configured correctly in the Twilio console.

### ECS `force-new-deployment` skipped in GH Actions
**Cause:** Transient `aws ecs list-services` API error during the deploy job — the script gets an empty response and skips the ECS update.
**Fix:** Manually force deploy (see section 3) or re-run the workflow:
```bash
gh run rerun <run-id> --failed
```

### ECS task fails to start / stuck in PENDING
**Check:** Task stopped reason via:
```bash
aws ecs describe-tasks \
  --cluster vak-cluster-prod \
  --tasks $(aws ecs list-tasks --cluster vak-cluster-prod --query 'taskArns[0]' --output text --region us-west-2) \
  --region us-west-2 \
  --query 'tasks[0].stoppedReason'
```
**Common causes:** missing secrets, ECR pull failure, OOM.

---

## 6. Twilio Configuration

### Check phone number webhooks
```bash
ACCOUNT_SID="ACd00787e66384ec2d2ed3e262748525af"
AUTH_TOKEN=$(aws secretsmanager get-secret-value --secret-id vak/twilio-auth-token --region us-west-2 --query 'SecretString' --output text)

curl -s "https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/IncomingPhoneNumbers.json" \
  -u "$ACCOUNT_SID:$AUTH_TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for n in d['incoming_phone_numbers']:
    print(n['phone_number'], '| voice:', n.get('voice_url'), '| sms:', n.get('sms_url'))
"
```

### Update a phone number's webhook
```bash
# Example: update voice URL for +15104054454
curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/$ACCOUNT_SID/IncomingPhoneNumbers/PN7bee054c9afaba030bebb5936d0ad422.json" \
  -u "$ACCOUNT_SID:$AUTH_TOKEN" \
  -d "VoiceUrl=https://api.groommate.ai/twilio/twiml" \
  -d "VoiceMethod=POST"
```

---

## 7. Secrets

All secrets are in AWS Secrets Manager (`us-west-2`):

| Secret | ARN suffix |
|--------|-----------|
| Deepgram API Key | `vak/deepgram-api-key` |
| Twilio Auth Token | `vak/twilio-auth-token` |

```bash
aws secretsmanager get-secret-value --secret-id vak/deepgram-api-key --region us-west-2 --query 'SecretString' --output text
aws secretsmanager get-secret-value --secret-id vak/twilio-auth-token --region us-west-2 --query 'SecretString' --output text
```

---

## 8. CI/CD Pipeline

```
main → alpha (auto, fast-forward)
alpha → beta  (PR required)
beta  → prod  (auto, fast-forward)
```

- **deploy-vakdeepgram.yml** — builds Docker image, pushes to ECR, force-deploys ECS (triggers on push to any branch)
- **deploy-vak-infra.yml** — deploys CDK stacks (triggers on push to VakInfra/** changes)
- **promote.yml** — handles branch promotion

### Re-run a failed workflow
```bash
gh run list --workflow=deploy-vakdeepgram.yml --limit 5
gh run rerun <run-id> --failed
```

---

## 9. CloudWatch Dashboards

- `VakDeepGram-Service-Prod` — ECS CPU/Memory, request counts
- `VakInfra-Core-Prod` — ALB latency, 5xx errors

```bash
# Open in browser
aws cloudwatch get-dashboard --dashboard-name VakDeepGram-Service-Prod --region us-west-2
```

Alarms → SNS → `nag@tutzi.ai`
