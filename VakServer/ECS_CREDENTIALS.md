# AWS Credentials in ECS Fargate

## How ECS Fargate Provides Credentials

In ECS Fargate, containers **automatically receive AWS credentials** through **IAM Task Roles**. No manual credential configuration is needed in your application code.

### The Process

1. **Task Role Assignment**: When you create an ECS Task Definition, you assign an IAM role (called the "Task Role") to it.

2. **Credential Injection**: ECS automatically injects temporary credentials into each running container via:
   - **ECS Task Metadata Endpoint**: `http://169.254.170.2/v2/credentials/{task-role-credentials-path}`
   - This endpoint is only accessible from within the container

3. **AWS SDK Auto-Discovery**: The AWS SDK automatically discovers and uses these credentials through the **default credential provider chain**:
   - Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
   - ECS Task Role credentials (via metadata endpoint)
   - EC2 instance profile credentials
   - AWS credentials file (`~/.aws/credentials`)
   - Container credentials (for ECS)

### Your Infrastructure Setup

Looking at your CDK code (`VakInfra/lib/vak-stack.ts` and `vak-app-stack.ts`), you already have this configured correctly:

```typescript
// Task role with permissions for Bedrock, Transcribe, Polly, S3, DynamoDB
const taskRole = new iam.Role(this, 'TaskRole', {
  assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
});

// Grant permissions...
taskRole.addToPolicy(/* Bedrock permissions */);
taskRole.addToPolicy(/* Transcribe permissions */);
taskRole.addToPolicy(/* Polly permissions */);
taskRole.addToPolicy(/* API Gateway permissions */);
artifactsBucket.grantReadWrite(taskRole);
sessionsTable.grantReadWriteData(taskRole);

// Assign to task definition
const taskDefinition = new ecs.FargateTaskDefinition(this, 'VakTaskDefinition', {
  executionRole: taskExecutionRole,  // For pulling images, CloudWatch logs
  taskRole: taskRole,                 // For your application to access AWS services
});
```

### Your Application Code

Your application code is **already correct** for ECS Fargate! You're using the default credential provider chain:

```typescript
// websocket-handler.ts
const ddbClient = new DynamoDBClient({ region: process.env.REGION || 'us-west-2' });
// No explicit credentials - uses default provider chain ✅

// message-handlers.ts
const bedrockClient = new BedrockRuntimeClient({ region });
const transcribeClient = new TranscribeStreamingClient({ region });
const pollyClient = new PollyClient({ region });
// No explicit credentials - uses default provider chain ✅
```

The AWS SDK v3 automatically detects and uses the ECS Task Role credentials when running in Fargate.

## Differences: Local vs ECS Fargate

### Local Development
- **Option 1**: Mount AWS credentials file
  ```bash
  docker run -v ~/.aws:/root/.aws:ro -e AWS_PROFILE=default ...
  ```

- **Option 2**: Pass environment variables
  ```bash
  docker run -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... ...
  ```

### ECS Fargate (Production)
- **No configuration needed!** ✅
- ECS automatically provides credentials via the Task Role
- The AWS SDK automatically discovers them
- Credentials are temporary and rotated automatically
- More secure than static credentials

## Important Notes

1. **Task Role vs Execution Role**:
   - **Task Role** (`taskRole`): Used by your application code to access AWS services (Bedrock, DynamoDB, etc.)
   - **Execution Role** (`executionRole`): Used by ECS to pull images from ECR and write logs to CloudWatch

2. **No Code Changes Needed**: Your application code doesn't need any changes between local and ECS deployments. The AWS SDK handles credential discovery automatically.

3. **Security**: Task Role credentials are:
   - Temporary (rotated automatically)
   - Scoped to the specific task
   - Only accessible from within the container
   - Automatically revoked when the task stops

## Verification

To verify credentials are working in ECS Fargate, check CloudWatch Logs for your service. If you see credential errors, check:

1. Task Role is assigned to the Task Definition
2. Task Role has the necessary permissions
3. Task is running (not stopped/failed)

## References

- [AWS ECS Task IAM Roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [AWS SDK Default Credential Provider Chain](https://docs.aws.amazon.com/sdk-for-javascript/v3/developer-guide/setting-credentials-node.html)
- [ECS Task Metadata Endpoint](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4-fargate.html)
