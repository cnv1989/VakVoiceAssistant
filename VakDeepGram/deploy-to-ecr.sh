#!/bin/bash
set -e

# Configuration
REGION="${AWS_REGION:-us-west-2}"
REPO_NAME="vak-deepgram"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== VakDeepGram ECR Deployment ===${NC}"

# Get AWS account ID
echo -e "${YELLOW}Getting AWS account ID...${NC}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}Error: Failed to get AWS account ID. Make sure AWS CLI is configured.${NC}"
    exit 1
fi
echo "AWS Account ID: $AWS_ACCOUNT_ID"

# Construct ECR repository URI
ECR_REPO_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO_NAME}"
echo "ECR Repository URI: $ECR_REPO_URI"

# Authenticate Docker to ECR
echo -e "${YELLOW}Authenticating Docker to ECR...${NC}"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO_URI"

# Check if repository exists, create if it doesn't
echo -e "${YELLOW}Checking if ECR repository exists...${NC}"
if ! aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" &>/dev/null; then
    echo "Repository does not exist. Creating it..."
    aws ecr create-repository \
        --repository-name "$REPO_NAME" \
        --region "$REGION" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability MUTABLE
    echo "Repository created successfully."
else
    echo "Repository already exists."
fi

# Build Docker image for linux/amd64 platform (required for ECS Fargate)
echo -e "${YELLOW}Building Docker image for linux/amd64 platform...${NC}"
docker build --platform linux/amd64 -t "${REPO_NAME}:${IMAGE_TAG}" .

# Tag image for ECR
echo -e "${YELLOW}Tagging image for ECR...${NC}"
docker tag "${REPO_NAME}:${IMAGE_TAG}" "${ECR_REPO_URI}:${IMAGE_TAG}"

# Push image to ECR
echo -e "${YELLOW}Pushing image to ECR...${NC}"
docker push "${ECR_REPO_URI}:${IMAGE_TAG}"

echo -e "${GREEN}✓ Deployment complete!${NC}"
echo -e "${GREEN}Image URI: ${ECR_REPO_URI}:${IMAGE_TAG}${NC}"
echo ""
echo -e "${BLUE}The image is now available for use in VakAppStack.${NC}"
