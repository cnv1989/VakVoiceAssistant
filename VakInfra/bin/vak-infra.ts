#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VakNetworkStack } from '../lib/vak-network-stack';
import { VakAppStack, ExistingTableNames } from '../lib/vak-app-stack';
import { VakMonitoringStack } from '../lib/vak-monitoring-stack';

const app = new cdk.App();

/** Read a value from `-c key=value` CDK context, falling back to an env var, then a default. */
function opt(contextKey: string, envKey: string, fallback?: string): string | undefined {
  const fromContext = app.node.tryGetContext(contextKey);
  if (fromContext !== undefined) return String(fromContext);
  return process.env[envKey] ?? fallback;
}

function flag(contextKey: string, envKey: string): boolean {
  const value = opt(contextKey, envKey);
  return value === 'true' || value === '1';
}

const region = opt('awsRegion', 'AWS_REGION', process.env.CDK_DEFAULT_REGION || 'us-west-2');
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region };

const stackName = opt('stackName', 'VAK_STACK_NAME', 'Vak')!;
const stage = opt('stage', 'VAK_STAGE', 'production')!;

const existingTables: ExistingTableNames = {
  squareAccount: opt('squareAccountTable', 'EXISTING_SQUARE_ACCOUNT_TABLE'),
  setmoreAccount: opt('setmoreAccountTable', 'EXISTING_SETMORE_ACCOUNT_TABLE'),
  businessNumber: opt('businessNumberTable', 'EXISTING_BUSINESS_NUMBER_TABLE'),
  businessAutomations: opt('businessAutomationsTable', 'EXISTING_BUSINESS_AUTOMATIONS_TABLE'),
  callRecord: opt('callRecordTable', 'EXISTING_CALL_RECORD_TABLE'),
  voiceCustomer: opt('voiceCustomerTable', 'EXISTING_VOICE_CUSTOMER_TABLE'),
  userBookingLink: opt('userBookingLinkTable', 'EXISTING_USER_BOOKING_LINK_TABLE'),
};

const networkStack = new VakNetworkStack(app, `${stackName}NetworkStack`, {
  env,
  ecrRepositoryName: opt('ecrRepositoryName', 'ECR_REPOSITORY_NAME'),
});

const appStack = new VakAppStack(app, `${stackName}AppStack`, {
  env,
  networkStack,
  stage,
  imageTag: opt('imageTag', 'IMAGE_TAG', 'latest'),

  domainName: opt('domainName', 'DOMAIN_NAME'),
  hostedZoneDomain: opt('hostedZoneDomain', 'HOSTED_ZONE_DOMAIN'),
  certificateArn: opt('certificateArn', 'CERTIFICATE_ARN'),

  apiKey: opt('apiKey', 'API_KEY'),
  enableTwilioOnlyAccess: flag('enableTwilioOnlyAccess', 'ENABLE_TWILIO_ONLY_ACCESS'),

  deepgramApiKey: opt('deepgramApiKey', 'DEEPGRAM_API_KEY'),
  deepgramApiKeySecretArn: opt('deepgramApiKeySecretArn', 'DEEPGRAM_API_KEY_SECRET_ARN'),

  llmProvider: opt('llmProvider', 'LLM_PROVIDER', 'bedrock'),
  llmModelId: opt('llmModelId', 'LLM_MODEL_ID'),
  anthropicApiKey: opt('anthropicApiKey', 'ANTHROPIC_API_KEY'),
  anthropicApiKeySecretArn: opt('anthropicApiKeySecretArn', 'ANTHROPIC_API_KEY_SECRET_ARN'),
  openaiApiKey: opt('openaiApiKey', 'OPENAI_API_KEY'),
  openaiApiKeySecretArn: opt('openaiApiKeySecretArn', 'OPENAI_API_KEY_SECRET_ARN'),

  deepgramSpeakingProvider: opt('deepgramSpeakingProvider', 'DEEPGRAM_SPEAKING_PROVIDER'),
  deepgramSpeakingModelId: opt('deepgramSpeakingModelId', 'DEEPGRAM_SPEAKING_MODEL_ID'),
  deepgramSpeakingVoiceId: opt('deepgramSpeakingVoiceId', 'DEEPGRAM_SPEAKING_VOICE_ID'),
  deepgramThinkingProvider: opt('deepgramThinkingProvider', 'DEEPGRAM_THINKING_PROVIDER'),
  deepgramThinkingModel: opt('deepgramThinkingModel', 'DEEPGRAM_THINKING_MODEL'),

  twilioAccountSid: opt('twilioAccountSid', 'TWILIO_ACCOUNT_SID'),
  twilioFromNumber: opt('twilioFromNumber', 'TWILIO_FROM_NUMBER'),
  twilioWhatsappNumber: opt('twilioWhatsappNumber', 'TWILIO_WHATSAPP_NUMBER'),
  twilioAuthToken: opt('twilioAuthToken', 'TWILIO_AUTH_TOKEN'),
  twilioAuthTokenSecretArn: opt('twilioAuthTokenSecretArn', 'TWILIO_AUTH_TOKEN_SECRET_ARN'),

  chatApiKey: opt('chatApiKey', 'CHAT_API_KEY'),

  businessName: opt('businessName', 'BUSINESS_NAME'),
  businessVertical: opt('businessVertical', 'BUSINESS_VERTICAL', 'generic'),
  businessRoleDescription: opt('businessRoleDescription', 'BUSINESS_ROLE_DESCRIPTION'),
  agentcoreMemoryId: opt('agentcoreMemoryId', 'AGENTCORE_MEMORY_ID'),

  existingTables,
  cognitoDomainPrefix: opt('cognitoDomainPrefix', 'COGNITO_DOMAIN_PREFIX'),
});
appStack.addDependency(networkStack);

const monitoringStack = new VakMonitoringStack(app, `${stackName}MonitoringStack`, {
  env,
  appStack,
  alarmEmail: opt('alarmEmail', 'ALARM_EMAIL'),
});
monitoringStack.addDependency(appStack);
