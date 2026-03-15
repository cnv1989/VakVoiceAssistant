#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VakNetworkStack } from '../lib/vak-network-stack';
import { VakAppStack } from '../lib/vak-app-stack';
import { VakMonitoringStack } from '../lib/vak-monitoring-stack';
import { VakDnsStack } from '../lib/vak-dns-stack';

const app = new cdk.App();

const env = { region: 'us-west-2' };

// ─── Shared secrets (same keys used across all stages) ───────────────────────
const deepgramApiKeySecretArn = 'arn:aws:secretsmanager:us-west-2:844341423871:secret:vak/deepgram-api-key-l5hv2P';
const twilioAuthTokenSecretArn = 'arn:aws:secretsmanager:us-west-2:844341423871:secret:vak/twilio-auth-token-odOYCC';

const enableTwilioOnlyAccess =
  app.node.tryGetContext('enableTwilioOnlyAccess') === 'true' ||
  process.env.ENABLE_TWILIO_ONLY_ACCESS === 'true';

// ─── Shared DNS stack (groommate.ai hosted zone + wildcard cert) ──────────────
// Deploy once; all stage stacks share this zone and certificate.
const dnsStack = new VakDnsStack(app, 'VakDnsStack', { env });

// ─── Shared network stack (VPC + ECR repo) ────────────────────────────────────
// All stage ECS clusters run inside the same VPC (saves NAT gateway costs).
const networkStack = new VakNetworkStack(app, 'VakNetworkStack', { env });

// ─── Per-stage configuration ──────────────────────────────────────────────────
//
// amplifyEnvId: the Amplify Gen 2 App ID suffix embedded in DynamoDB table names.
//   Format:  <ModelName>-<amplifyEnvId>-NONE
//   prod:    pxy5meaaojbaxjwedt6v6oidw4  (existing, already deployed)
//   beta/alpha: run `aws dynamodb list-tables | grep BusinessNumber` after the
//               Amplify branch first deploys, then update these values.
//
// Domain layout:
//   prod  →  app.groommate.ai   (Integrin frontend)  api.groommate.ai  (VakDeepGram)
//   beta  →  beta.groommate.ai                        beta-api.groommate.ai
//   alpha →  alpha.groommate.ai                       alpha-api.groommate.ai
//
// Amplify custom domains are configured in the Amplify console (Amplify
// auto-provisions CloudFront certs in us-east-1).
// Route53 CNAME records for Amplify custom domains are added automatically
// by Amplify when you add the domain in the console.
//
const stageConfigs: Array<{
  stage: string;
  amplifyEnvId: string;
  apiDomain: string;
  cognitoDomainPrefix: string;
}> = [
  {
    stage: 'prod',
    amplifyEnvId: 'pxy5meaaojbaxjwedt6v6oidw4',
    apiDomain: 'api.groommate.ai',
    cognitoDomainPrefix: 'groommate-auth-prod',
  },
  {
    stage: 'beta',
    // TODO: Replace PLACEHOLDER after Amplify beta branch deploys:
    //   aws dynamodb list-tables --region us-west-2 | grep BusinessNumber
    amplifyEnvId: app.node.tryGetContext('betaAmplifyEnvId') || 'PLACEHOLDER_BETA_ENV_ID',
    apiDomain: 'beta-api.groommate.ai',
    cognitoDomainPrefix: 'groommate-auth-beta',
  },
  {
    stage: 'alpha',
    // TODO: Replace PLACEHOLDER after Amplify alpha branch deploys:
    //   aws dynamodb list-tables --region us-west-2 | grep BusinessNumber
    amplifyEnvId: app.node.tryGetContext('alphaAmplifyEnvId') || 'PLACEHOLDER_ALPHA_ENV_ID',
    apiDomain: 'alpha-api.groommate.ai',
    cognitoDomainPrefix: 'groommate-auth-alpha',
  },
];

for (const cfg of stageConfigs) {
  const cap = cfg.stage.charAt(0).toUpperCase() + cfg.stage.slice(1);

  const appStack = new VakAppStack(app, `VakAppStack-${cap}`, {
    env,
    networkStack,
    stage: cfg.stage,
    amplifyEnvId: cfg.amplifyEnvId,
    apiDomain: cfg.apiDomain,
    hostedZone: dnsStack.hostedZone,
    certificateArn: dnsStack.wildcardCertificate.certificateArn,
    deepgramApiKeySecretArn,
    twilioAuthTokenSecretArn,
    enableTwilioOnlyAccess,
    cognitoDomainPrefix: cfg.cognitoDomainPrefix,
  });
  appStack.addDependency(networkStack);
  appStack.addDependency(dnsStack);

  const monitoringStack = new VakMonitoringStack(app, `VakMonitoringStack-${cap}`, {
    env,
    appStack,
  });
  monitoringStack.addDependency(appStack);
}
