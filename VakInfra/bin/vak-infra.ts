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
// Optional: Provide Deepgram API key
// Pass via context: cdk deploy -c deepgramApiKey=your-api-key
// Or set as environment variable: DEEPGRAM_API_KEY=your-api-key cdk deploy
const deepgramApiKey = app.node.tryGetContext('deepgramApiKey') || process.env.DEEPGRAM_API_KEY;

// Optional: Provide Twilio auth token
// Pass via context: cdk deploy -c twilioAuthToken=your-token
// Or set as environment variable: TWILIO_AUTH_TOKEN=your-token cdk deploy
const twilioAuthToken = app.node.tryGetContext('twilioAuthToken') || process.env.TWILIO_AUTH_TOKEN;

// Optional: Provide ACM certificate ARN for HTTPS/WSS support
// First create certificate in ACM (us-west-2 region):
//   See CERTIFICATE_SETUP.md for instructions
// Then pass it via context: cdk deploy -c certificateArn=arn:aws:acm:us-west-2:...
// Or set it as an environment variable: CERTIFICATE_ARN=arn:aws:acm:us-west-2:... cdk deploy
const certificateArn = app.node.tryGetContext('certificateArn') || process.env.CERTIFICATE_ARN;

// Optional: Enable WAF protection to restrict access to Twilio IPs only
// Set to true to enable IP allowlist (only Twilio can access)
// Pass via context: cdk deploy -c enableTwilioOnlyAccess=true
// Or set as environment variable: ENABLE_TWILIO_ONLY_ACCESS=true cdk deploy
const enableTwilioOnlyAccess = app.node.tryGetContext('enableTwilioOnlyAccess') === 'true' || 
                                app.node.tryGetContext('enableTwilioOnlyAccess') === true ||
                                process.env.ENABLE_TWILIO_ONLY_ACCESS === 'true';

const appStack = new VakAppStack(app, 'VakAppStack', {
  env,
  networkStack,
  deepgramApiKey,
  twilioAuthToken,
  certificateArn,
  enableTwilioOnlyAccess,
});

// Add explicit dependency
appStack.addDependency(networkStack);
