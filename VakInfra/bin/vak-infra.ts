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

// Hardcoded secret ARNs from AWS Secrets Manager
const deepgramApiKeySecretArn = 'arn:aws:secretsmanager:us-west-2:844341423871:secret:vak/deepgram-api-key-l5hv2P';
const twilioAuthTokenSecretArn = 'arn:aws:secretsmanager:us-west-2:844341423871:secret:vak/twilio-auth-token-odOYCC';

// Optional: Provide Deepgram API key (deprecated, use deepgramApiKeySecretArn instead)
// Pass via context: cdk deploy -c deepgramApiKey=your-api-key
// Or set as environment variable: DEEPGRAM_API_KEY=your-api-key cdk deploy
const deepgramApiKey = app.node.tryGetContext('deepgramApiKey') || process.env.DEEPGRAM_API_KEY;

// Optional: Provide Twilio auth token (deprecated, use twilioAuthTokenSecretArn instead)
// Pass via context: cdk deploy -c twilioAuthToken=your-token
// Or set as environment variable: TWILIO_AUTH_TOKEN=your-token cdk deploy
const twilioAuthToken = app.node.tryGetContext('twilioAuthToken') || process.env.TWILIO_AUTH_TOKEN;

// Hardcoded ACM certificate ARN for HTTPS/WSS support
const certificateArn = 'arn:aws:acm:us-west-2:844341423871:certificate/b290a998-200c-42b5-a2e1-66bfcda715b2';

// Optional: Enable WAF protection to restrict access to Twilio IPs only
// Set to true to enable IP allowlist (only Twilio can access)
// Pass via context: cdk deploy -c enableTwilioOnlyAccess=true
// Or set as environment variable: ENABLE_TWILIO_ONLY_ACCESS=true cdk deploy
const enableTwilioOnlyAccess = app.node.tryGetContext('enableTwilioOnlyAccess') === 'true' || 
                                app.node.tryGetContext('enableTwilioOnlyAccess') === true ||
                                process.env.ENABLE_TWILIO_ONLY_ACCESS === 'true';

const cognitoHost = app.node.tryGetContext('cognitoHost') || process.env.COGNITO_HOST || 'vak.tutzi.ai';
const cognitoDomainPrefix = app.node.tryGetContext('cognitoDomainPrefix') ||
  process.env.COGNITO_DOMAIN_PREFIX ||
  'vak-auth';

const appStack = new VakAppStack(app, 'VakAppStack', {
  env,
  networkStack,
  deepgramApiKeySecretArn,
  deepgramApiKey,
  twilioAuthTokenSecretArn,
  twilioAuthToken,
  certificateArn,
  enableTwilioOnlyAccess,
  cognitoHost,
  cognitoDomainPrefix,
});

// Add explicit dependency
appStack.addDependency(networkStack);
