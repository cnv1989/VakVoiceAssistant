#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VakNetworkStack } from '../lib/vak-network-stack';
import { VakAppStack } from '../lib/vak-app-stack';

const app = new cdk.App();

const env = {
  region: 'us-west-2',
};

// Network stack: VPC and ECR repository
const networkStack = new VakNetworkStack(app, 'VakNetworkStack', {
  env,
});

// Application stack: ECS, DynamoDB, S3, API Gateway, etc.
// Depends on network stack
const appStack = new VakAppStack(app, 'VakAppStack', {
  env,
  networkStack,
});

// Add explicit dependency
appStack.addDependency(networkStack);
