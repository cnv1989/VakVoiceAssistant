# Deployment Guide: VakServer to ECS Fargate

This guide covers deploying the VakServer container to ECS Fargate via ECR.

## Prerequisites

1. **AWS CLI configured** with appropriate credentials
2. **Docker** installed and running
3. **Node.js 20+** installed
4. **AWS CDK CLI** installed: `npm install -g aws-cdk`

## Deployment Process Overview

The deployment process has two main steps:

1. **Push Docker image to ECR** (container registry)
2. **Deploy/Update CDK stack** (creates/updates ECS service with the new image)

## Step 1: Push Image to ECR

### Option A: Automated Script (Recommended)

The easiest way is to use the provided script:

```bash
cd VakServer
npm run deploy:ecr
```

Or run directly:

```bash
cd VakServer
./deploy-to-ecr.sh
```

This script will:
- Get your AWS account ID
- Authenticate Docker to ECR
- Create the ECR repository if it doesn't exist
- Build the Docker image for `linux/amd64` platform (required for ECS Fargate)
- Tag the image
- Push the image to ECR

### Option B: Custom Tag/Region

To deploy with a specific tag or region:

```bash
cd VakServer
AWS_REGION=us-east-1 IMAGE_TAG=v1.0.0 npm run deploy:ecr
```

### Option C: Manual Steps

If you prefer manual control:

```bash
cd VakServer

# 1. Get AWS account ID and construct ECR URI
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-west-2"
REPO_NAME="vak-server"
ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"

# 2. Authenticate Docker to ECR
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REPO_URI"

# 3. Create ECR repository if it doesn't exist
aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" || \
  aws ecr create-repository --repository-name "$REPO_NAME" --region "$REGION"

# 4. Build image for linux/amd64 (required for ECS Fargate)
docker build --platform linux/amd64 -t "${REPO_NAME}:latest" .

# 5. Tag image for ECR
docker tag "${REPO_NAME}:latest" "${ECR_REPO_URI}:latest"

# 6. Push to ECR
docker push "${ECR_REPO_URI}:latest"
```

## Step 2: Deploy/Update ECS Infrastructure

After pushing the image to ECR, deploy or update the CDK stack:

```bash
cd VakInfra

# 1. Install dependencies (if not already done)
npm install

# 2. Bootstrap CDK (only needed once per account/region)
cdk bootstrap aws://ACCOUNT-ID/us-west-2

# 3. Build TypeScript
npm run build

# 4. Review changes (optional)
cdk diff

# 5. Deploy the stack
npm run deploy
# Or: cdk deploy
```

The CDK stack will:
- Create/update the ECS Task Definition with the new image
- Create/update the ECS Service
- Create/update all supporting infrastructure (VPC, Load Balancer, API Gateway, etc.)

### First-Time Deployment

On first deployment, the CDK will create:
- VPC with public/private subnets
- ECS Cluster
- ECR Repository (if using `vak-stack.ts` with DockerImageAsset)
- ECS Task Definition and Service
- Application Load Balancer
- API Gateway WebSocket API
- DynamoDB table
- S3 bucket
- IAM roles

### Subsequent Deployments

When you push a new image and redeploy:
- ECS will automatically pull the new image
- ECS will perform a rolling update (start new tasks, then stop old ones)
- Zero downtime if health checks pass

## Step 3: Verify Deployment

### Check ECS Service Status

```bash
# Get cluster name from CDK outputs or use default
CLUSTER_NAME="vak-cluster"
SERVICE_NAME="VakService"  # Or check actual service name in AWS Console

# Check service status
aws ecs describe-services \
  --cluster "$CLUSTER_NAME" \
  --services "$SERVICE_NAME" \
  --region us-west-2

# Check running tasks
aws ecs list-tasks \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --region us-west-2
```

### Check Container Logs

```bash
# Get task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --region us-west-2 \
  --query 'taskArns[0]' --output text)

# Get log stream name
LOG_GROUP="/ecs/vak-server"
LOG_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP" \
  --order-by LastEventTime \
  --descending \
  --max-items 1 \
  --query 'logStreams[0].logStreamName' \
  --output text)

# View logs
aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" \
  --region us-west-2
```

Or use CloudWatch Console to view logs.

### Test Health Endpoint

```bash
# Get ALB DNS from CDK outputs
ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name VakStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AlbDns`].OutputValue' \
  --output text \
  --region us-west-2)

# Test health endpoint
curl http://${ALB_DNS}/health
```

## Complete Deployment Workflow

Here's a complete workflow for deploying updates:

```bash
# 1. Make your code changes in VakServer
cd VakServer
# ... make changes ...

# 2. Build and push to ECR
npm run deploy:ecr

# 3. Deploy infrastructure (if needed) or force ECS update
cd ../VakInfra
npm run deploy

# 4. Force new deployment (if CDK doesn't detect changes)
# This forces ECS to pull the latest image even if tag is the same
aws ecs update-service \
  --cluster vak-cluster \
  --service VakService \
  --force-new-deployment \
  --region us-west-2
```

## Using Version Tags (Recommended)

For better version control, use version tags instead of `latest`:

```bash
# 1. Push with version tag
cd VakServer
IMAGE_TAG=v1.2.3 npm run deploy:ecr

# 2. Update CDK to use the version tag
# Edit VakInfra/lib/vak-app-stack.ts:
#   image: ecs.ContainerImage.fromEcrRepository(ecrRepo, 'v1.2.3'),

# 3. Deploy CDK
cd ../VakInfra
npm run deploy
```

Or use git commit SHA:

```bash
VERSION=$(git rev-parse --short HEAD)
cd VakServer
IMAGE_TAG=$VERSION npm run deploy:ecr
```

## Troubleshooting

### Image Pull Errors

If ECS can't pull the image:
- Verify ECR repository exists and image was pushed
- Check Execution Role has `AmazonECSTaskExecutionRolePolicy`
- Verify image tag matches what's in Task Definition

### Container Won't Start

- Check CloudWatch Logs for errors
- Verify health check endpoint is accessible
- Check environment variables are set correctly
- Verify Task Role has necessary permissions

### Credentials Errors

- Verify Task Role is assigned to Task Definition
- Check Task Role has permissions for Bedrock, Transcribe, Polly, DynamoDB, S3
- See `ECS_CREDENTIALS.md` for details

### Force New Deployment

If ECS isn't picking up a new image with the same tag:

```bash
aws ecs update-service \
  --cluster vak-cluster \
  --service VakService \
  --force-new-deployment \
  --region us-west-2
```

## CDK Stack Structure

Your infrastructure uses one of two stack configurations:

1. **`vak-stack.ts`**: Single stack with DockerImageAsset (auto-builds image)
2. **`vak-app-stack.ts`**: Separate stacks, uses existing ECR image

For manual ECR pushes, use the approach in this guide. For automatic builds during CDK deploy, use `vak-stack.ts` with `DockerImageAsset`.

## References

- [AWS ECR Documentation](https://docs.aws.amazon.com/ecr/)
- [AWS ECS Deployment](https://docs.aws.amazon.com/ecs/latest/developerguide/deployments.html)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
