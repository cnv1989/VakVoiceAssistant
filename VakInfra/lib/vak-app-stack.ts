import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as elbv2Actions from 'aws-cdk-lib/aws-elasticloadbalancingv2-actions';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as certificatemanager from 'aws-cdk-lib/aws-certificatemanager';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as route53Targets from 'aws-cdk-lib/aws-route53-targets';
import { Construct } from 'constructs';
import { VakNetworkStack } from './vak-network-stack';

/**
 * Table names to import instead of creating fresh ones — use this if you
 * already run a companion business-management app (e.g. the Integrin
 * dashboard) that owns these tables. Any field left unset gets a brand-new
 * table created by this stack, so a from-scratch deployment works with zero
 * external dependencies.
 */
export interface ExistingTableNames {
  squareAccount?: string;
  setmoreAccount?: string;
  businessNumber?: string;
  businessAutomations?: string;
  callRecord?: string;
  voiceCustomer?: string;
  userBookingLink?: string;
}

export interface VakAppStackProps extends cdk.StackProps {
  networkStack: VakNetworkStack;

  /** Logical environment name used in resource names (e.g. 'production', 'staging'). Defaults to 'production'. */
  stage?: string;

  /** Docker image tag in the ECR repo to deploy. Defaults to 'latest'. */
  imageTag?: string;

  /**
   * Custom domain for the API (e.g. 'voice.example.com'). Omit to use the
   * ALB's auto-generated DNS name over plain HTTP/WS — fine for testing,
   * not recommended for production (no TLS).
   */
  domainName?: string;
  /**
   * Name of an EXISTING Route 53 public hosted zone that owns domainName
   * (e.g. 'example.com'). When set, CDK creates a DNS-validated ACM
   * certificate and an A record automatically.
   */
  hostedZoneDomain?: string;
  /** Pre-existing ACM certificate ARN — use instead of hostedZoneDomain if you manage certs yourself. */
  certificateArn?: string;

  /** Require an `X-Api-Key` header (checked by WAF) matching this value on every request except /health. */
  apiKey?: string;
  /** Restrict the ALB to Twilio's published Media Streams IP ranges (for phone-only deployments behind a domain no one else needs to reach). */
  enableTwilioOnlyAccess?: boolean;

  /** Deepgram API key (plaintext, only recommended for quick test deploys). */
  deepgramApiKey?: string;
  /** ARN of a Secrets Manager secret holding the Deepgram API key (recommended for production). */
  deepgramApiKeySecretArn?: string;

  /** LLM provider for the Strands agent (/chat + voice tool-calling): 'bedrock' (default), 'anthropic', or 'openai'. */
  llmProvider?: string;
  /** Overrides the provider's default model ID. */
  llmModelId?: string;
  anthropicApiKey?: string;
  anthropicApiKeySecretArn?: string;
  openaiApiKey?: string;
  openaiApiKeySecretArn?: string;

  /** TTS voice provider used by the Deepgram Voice Agent: 'eleven_labs' (default), 'deepgram', or any other Deepgram supports. */
  deepgramSpeakingProvider?: string;
  deepgramSpeakingModelId?: string;
  deepgramSpeakingVoiceId?: string;
  /** LLM bridge used *inside* the Deepgram Voice Agent (independent of llmProvider above). */
  deepgramThinkingProvider?: string;
  deepgramThinkingModel?: string;

  twilioAccountSid?: string;
  twilioFromNumber?: string;
  twilioWhatsappNumber?: string;
  twilioAuthToken?: string;
  twilioAuthTokenSecretArn?: string;

  /** API key required on the /chat REST endpoint. Leave unset to disable auth on /chat (fine for local testing only). */
  chatApiKey?: string;

  /** Business profile forwarded to the container — see providers/common/persona.py. */
  businessName?: string;
  businessVertical?: string;
  /** Full custom persona override, bypassing businessVertical presets. */
  businessRoleDescription?: string;

  /** Optional Bedrock AgentCore Memory ID for chat session persistence. */
  agentcoreMemoryId?: string;

  /** Import existing DynamoDB tables instead of creating new ones. */
  existingTables?: ExistingTableNames;

  /**
   * Cognito hosted-UI domain prefix for ALB-level auth in front of /ws and
   * /chat. Omit to disable (FastAPI's own OAuth/API-key checks still apply).
   */
  cognitoDomainPrefix?: string;
}

export class VakAppStack extends cdk.Stack {
  public readonly stage: string;
  public readonly cluster: ecs.Cluster;
  public readonly service: ecs.FargateService;
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly targetGroup: elbv2.ApplicationTargetGroup;
  public readonly sessionsTable: dynamodb.Table;
  public readonly artifactsBucket: s3.Bucket;
  public readonly serviceLogGroup: logs.LogGroup;
  public readonly taskRole: iam.Role;

  constructor(scope: Construct, id: string, props: VakAppStackProps) {
    super(scope, id, props);

    const stage = props.stage ?? 'production';
    const imageTag = props.imageTag ?? 'latest';
    const { vpc, deepgramEcrRepo } = props.networkStack;
    this.stage = stage;

    // ─── DynamoDB tables ───────────────────────────────────────────────────────
    // Schemas below match exactly what VakDeepGram's utils/*.py read and write
    // (see docs/ARCHITECTURE.md#data-model). Pass `existingTables` to import
    // tables owned by a separate app instead of creating fresh ones here.
    const existing = props.existingTables ?? {};

    const sessionsTable = new dynamodb.Table(this, 'SessionsTable', {
      tableName: `Vak-Sessions-${stage}`,
      partitionKey: { name: 'sid', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.sessionsTable = sessionsTable;

    const businessNumberTable = existing.businessNumber
      ? dynamodb.Table.fromTableName(this, 'BusinessNumberTable', existing.businessNumber)
      : new dynamodb.Table(this, 'BusinessNumberTable', {
          tableName: `Vak-BusinessNumber-${stage}`,
          partitionKey: { name: 'phoneNumber', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const squareAccountTable = existing.squareAccount
      ? dynamodb.Table.fromTableName(this, 'SquareAccountTable', existing.squareAccount)
      : new dynamodb.Table(this, 'SquareAccountTable', {
          tableName: `Vak-SquareAccount-${stage}`,
          partitionKey: { name: 'userId', type: dynamodb.AttributeType.STRING },
          sortKey: { name: 'merchantId', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const setmoreAccountTable = existing.setmoreAccount
      ? dynamodb.Table.fromTableName(this, 'SetmoreAccountTable', existing.setmoreAccount)
      : new dynamodb.Table(this, 'SetmoreAccountTable', {
          tableName: `Vak-SetmoreAccount-${stage}`,
          partitionKey: { name: 'accountId', type: dynamodb.AttributeType.STRING },
          sortKey: { name: 'userId', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const businessAutomationsTable = existing.businessAutomations
      ? dynamodb.Table.fromTableName(this, 'BusinessAutomationsTable', existing.businessAutomations)
      : new dynamodb.Table(this, 'BusinessAutomationsTable', {
          tableName: `Vak-BusinessAutomations-${stage}`,
          partitionKey: { name: 'merchantId', type: dynamodb.AttributeType.STRING },
          sortKey: { name: 'locationId', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const callRecordTable = existing.callRecord
      ? dynamodb.Table.fromTableName(this, 'CallRecordTable', existing.callRecord)
      : new dynamodb.Table(this, 'CallRecordTable', {
          tableName: `Vak-CallRecord-${stage}`,
          partitionKey: { name: 'callId', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const voiceCustomerTable = existing.voiceCustomer
      ? dynamodb.Table.fromTableName(this, 'VoiceCustomerTable', existing.voiceCustomer)
      : new dynamodb.Table(this, 'VoiceCustomerTable', {
          tableName: `Vak-VoiceCustomer-${stage}`,
          partitionKey: { name: 'customerId', type: dynamodb.AttributeType.STRING },
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const userBookingLinkTable = existing.userBookingLink
      ? dynamodb.Table.fromTableName(this, 'UserBookingLinkTable', existing.userBookingLink)
      : new dynamodb.Table(this, 'UserBookingLinkTable', {
          tableName: `Vak-UserBookingLink-${stage}`,
          partitionKey: { name: 'customerPhone', type: dynamodb.AttributeType.STRING },
          sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
          timeToLiveAttribute: 'ttl',
          billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    // ─── S3 artifacts bucket (transcripts + recordings) ──────────────────────
    const artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `vak-artifacts-${this.account}-${this.region}-${stage}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        { id: 'expire-call-sessions-30d', prefix: 'call-sessions/', expiration: cdk.Duration.days(30), enabled: true },
      ],
    });
    this.artifactsBucket = artifactsBucket;

    // ─── ECS Cluster ─────────────────────────────────────────────────────────
    const cluster = new ecs.Cluster(this, 'VakCluster', { vpc, clusterName: `vak-cluster-${stage}` });
    this.cluster = cluster;

    // ─── IAM roles ───────────────────────────────────────────────────────────
    const taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });
    deepgramEcrRepo.grantPull(taskExecutionRole);

    let deepgramSecret: secretsmanager.ISecret | undefined;
    let twilioSecret: secretsmanager.ISecret | undefined;

    if (props.deepgramApiKeySecretArn) {
      deepgramSecret = secretsmanager.Secret.fromSecretCompleteArn(this, 'DeepgramSecret', props.deepgramApiKeySecretArn);
      deepgramSecret.grantRead(taskExecutionRole);
    }
    if (props.twilioAuthTokenSecretArn) {
      twilioSecret = secretsmanager.Secret.fromSecretCompleteArn(this, 'TwilioSecret', props.twilioAuthTokenSecretArn);
      twilioSecret.grantRead(taskExecutionRole);
    }

    let anthropicSecret: secretsmanager.ISecret | undefined;
    if (props.anthropicApiKeySecretArn) {
      anthropicSecret = secretsmanager.Secret.fromSecretCompleteArn(this, 'AnthropicSecret', props.anthropicApiKeySecretArn);
      anthropicSecret.grantRead(taskExecutionRole);
    }
    let openaiSecret: secretsmanager.ISecret | undefined;
    if (props.openaiApiKeySecretArn) {
      openaiSecret = secretsmanager.Secret.fromSecretCompleteArn(this, 'OpenAiSecret', props.openaiApiKeySecretArn);
      openaiSecret.grantRead(taskExecutionRole);
    }

    this.taskRole = new iam.Role(this, 'TaskRole', { assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com') });
    const taskRole = this.taskRole;

    [
      sessionsTable, businessNumberTable, squareAccountTable, setmoreAccountTable,
      businessAutomationsTable, callRecordTable, voiceCustomerTable, userBookingLinkTable,
    ].forEach(t => t.grantReadWriteData(taskRole));
    artifactsBucket.grantReadWrite(taskRole);

    // Bedrock AgentCore Memory (session persistence for chat/WhatsApp)
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:InvokeAgent', 'bedrock:CreateMemory', 'bedrock:GetMemory', 'bedrock:ListMemories',
        'bedrock:DeleteMemory', 'bedrock:CreateSession', 'bedrock:GetSession', 'bedrock:ListSessions',
        'bedrock:DeleteSession', 'bedrock:PutEvents', 'bedrock:GetEvents',
      ],
      resources: ['*'],
    }));

    // Bedrock for the Strands agent (voice + chat). foundation-model/* spans
    // multiple regions because cross-region inference profiles route requests
    // to whichever region has capacity; inference-profile/* is always local.
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [
        'arn:aws:bedrock:us-east-1::foundation-model/*',
        'arn:aws:bedrock:us-west-2::foundation-model/*',
        'arn:aws:bedrock:us-east-2::foundation-model/*',
        `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
      ],
    }));

    // ─── ECS Task Definition ─────────────────────────────────────────────────
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'VakTaskDefinition', {
      memoryLimitMiB: 1024,
      cpu: 512,
      executionRole: taskExecutionRole,
      taskRole,
    });

    const serviceLogGroup = new logs.LogGroup(this, 'VakServiceLogGroup', {
      logGroupName: `/ecs/vak-service-${stage}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.serviceLogGroup = serviceLogGroup;

    const containerSecrets: { [key: string]: ecs.Secret } = {};
    if (deepgramSecret) containerSecrets.DEEPGRAM_API_KEY = ecs.Secret.fromSecretsManager(deepgramSecret);
    if (twilioSecret) containerSecrets.TWILIO_AUTH_TOKEN = ecs.Secret.fromSecretsManager(twilioSecret);
    if (anthropicSecret) containerSecrets.ANTHROPIC_API_KEY = ecs.Secret.fromSecretsManager(anthropicSecret);
    if (openaiSecret) containerSecrets.OPENAI_API_KEY = ecs.Secret.fromSecretsManager(openaiSecret);

    const apiHost = props.domainName ?? 'PLACEHOLDER'; // replaced with the ALB DNS name below if unset

    const container = taskDefinition.addContainer('VakDeepGram', {
      image: ecs.ContainerImage.fromEcrRepository(deepgramEcrRepo, imageTag),
      cpu: 512,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'vak-deepgram', logGroup: serviceLogGroup }),
      environment: {
        HOST: '0.0.0.0',
        PORT: '8080',
        LOG_LEVEL: stage === 'production' ? 'info' : 'debug',
        ENVIRONMENT: stage === 'production' ? 'production' : 'staging',
        AWS_REGION: this.region,

        ...(props.businessName ? { BUSINESS_NAME: props.businessName } : {}),
        BUSINESS_VERTICAL: props.businessVertical ?? 'generic',
        ...(props.businessRoleDescription ? { BUSINESS_ROLE_DESCRIPTION: props.businessRoleDescription } : {}),

        LLM_PROVIDER: props.llmProvider ?? 'bedrock',
        ...(props.llmModelId ? { LLM_MODEL_ID: props.llmModelId } : {}),

        DEEPGRAM_AGENT_LANGUAGE: 'en',
        DEEPGRAM_LISTENING_MODEL: 'flux-general-en',
        DEEPGRAM_LISTENING_VERSION: 'v2',
        DEEPGRAM_THINKING_PROVIDER: props.deepgramThinkingProvider ?? 'google',
        DEEPGRAM_THINKING_MODEL: props.deepgramThinkingModel ?? 'gemini-2.5-flash',
        DEEPGRAM_SPEAKING_PROVIDER: props.deepgramSpeakingProvider ?? 'eleven_labs',
        DEEPGRAM_SPEAKING_MODEL_ID: props.deepgramSpeakingModelId ?? 'eleven_flash_v2_5',
        DEEPGRAM_SPEAKING_VOICE_ID: props.deepgramSpeakingVoiceId ?? 'cgSgspJ2msm6clMCkdW9',
        DEEPGRAM_INPUT_SAMPLE_RATE: '48000',
        DEEPGRAM_OUTPUT_SAMPLE_RATE: '24000',

        ...(props.twilioAccountSid ? { TWILIO_ACCOUNT_SID: props.twilioAccountSid } : {}),
        ...(props.twilioFromNumber ? { TWILIO_FROM_NUMBER: props.twilioFromNumber } : {}),
        TWILIO_WHATSAPP_NUMBER: props.twilioWhatsappNumber ?? '+14155238886',

        RECORDINGS_BUCKET: artifactsBucket.bucketName,
        RECORDINGS_KEY_PREFIX: 'call-sessions',

        BUSINESS_NUMBER_TABLE: businessNumberTable.tableName,
        SQUARE_ACCOUNT_TABLE: squareAccountTable.tableName,
        SETMORE_ACCOUNT_TABLE: setmoreAccountTable.tableName,
        BUSINESS_AUTOMATIONS_TABLE: businessAutomationsTable.tableName,
        CALL_RECORD_TABLE: callRecordTable.tableName,
        VOICE_CUSTOMER_TABLE: voiceCustomerTable.tableName,
        USER_BOOKING_LINK_TABLE: userBookingLinkTable.tableName,

        ALB_DNS: apiHost,

        ...(props.chatApiKey ? { CHAT_API_KEY: props.chatApiKey } : {}),
        ...(props.agentcoreMemoryId ? { AGENTCORE_MEMORY_ID: props.agentcoreMemoryId } : {}),
      },
      secrets: Object.keys(containerSecrets).length > 0 ? containerSecrets : undefined,
      healthCheck: {
        command: ['CMD-SHELL', 'curl -f http://localhost:8080/health || exit 1'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    if (!deepgramSecret) container.addEnvironment('DEEPGRAM_API_KEY', props.deepgramApiKey || '');
    if (!twilioSecret && props.twilioAuthToken) container.addEnvironment('TWILIO_AUTH_TOKEN', props.twilioAuthToken);
    if (!anthropicSecret && props.anthropicApiKey) container.addEnvironment('ANTHROPIC_API_KEY', props.anthropicApiKey);
    if (!openaiSecret && props.openaiApiKey) container.addEnvironment('OPENAI_API_KEY', props.openaiApiKey);

    container.addPortMappings({ containerPort: 8080, protocol: ecs.Protocol.TCP });

    // ─── ECS Service ─────────────────────────────────────────────────────────
    const service = new ecs.FargateService(this, 'VakService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      healthCheckGracePeriod: cdk.Duration.seconds(60),
    });
    this.service = service;

    // ─── Application Load Balancer ───────────────────────────────────────────
    const alb = new elbv2.ApplicationLoadBalancer(this, 'VakAlb', {
      vpc,
      internetFacing: true,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });
    this.alb = alb;

    const cfnAlb = alb.node.defaultChild as elbv2.CfnLoadBalancer;
    cfnAlb.loadBalancerAttributes = [
      { key: 'routing.http2.enabled', value: 'false' },
      { key: 'idle_timeout.timeout_seconds', value: '3600' },
    ];

    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'VakTargetGroup', {
      vpc,
      port: 8080,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        enabled: true,
        healthyHttpCodes: '200',
        path: '/health',
        protocol: elbv2.Protocol.HTTP,
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
      },
    });
    this.targetGroup = targetGroup;
    service.attachToApplicationTargetGroup(targetGroup);

    // ─── HTTP listener (port 80) ──────────────────────────────────────────────
    const httpListener = alb.addListener('VakListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });
    httpListener.addAction('BlockWsOverHttp', {
      priority: 5,
      conditions: [elbv2.ListenerCondition.pathPatterns(['/ws*'])],
      action: elbv2.ListenerAction.fixedResponse(403, {
        contentType: 'text/plain',
        messageBody: 'WebSocket auth requires WSS. Use wss://<host>/ws.',
      }),
    });
    httpListener.addAction('BlockChatOverHttp', {
      priority: 6,
      conditions: [elbv2.ListenerCondition.pathPatterns(['/chat*'])],
      action: elbv2.ListenerAction.fixedResponse(403, {
        contentType: 'text/plain',
        messageBody: 'Chat requires HTTPS. Use https://<host>/chat.',
      }),
    });

    // ─── HTTPS listener + optional custom domain/Cognito auth ────────────────
    // A cert is only created/attached when the caller opts in — plenty of
    // people just want to try Vak over the ALB's default HTTP/WS endpoint
    // first, and add a domain + TLS once they're ready to go live.
    let hostedZone: route53.IHostedZone | undefined;
    let certificate: elbv2.IListenerCertificate | undefined;

    if (props.certificateArn) {
      certificate = elbv2.ListenerCertificate.fromArn(props.certificateArn);
    } else if (props.domainName && props.hostedZoneDomain) {
      hostedZone = route53.HostedZone.fromLookup(this, 'HostedZone', { domainName: props.hostedZoneDomain });
      const cert = new certificatemanager.Certificate(this, 'ApiCertificate', {
        domainName: props.domainName,
        validation: certificatemanager.CertificateValidation.fromDns(hostedZone),
      });
      certificate = elbv2.ListenerCertificate.fromArn(cert.certificateArn);
    }

    if (certificate) {
      const httpsListener = alb.addListener('VakHttpsListener', {
        port: 443,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [certificate],
        defaultTargetGroups: [targetGroup],
      });

      if (props.cognitoDomainPrefix && props.domainName) {
        const userPool = new cognito.UserPool(this, 'VakUserPool', {
          selfSignUpEnabled: false,
          signInAliases: { email: true },
          userInvitation: {
            emailSubject: 'You are invited to Vak',
            emailBody: 'Your username is {username} and temporary password is {####}.',
          },
        });
        const userPoolClient = new cognito.UserPoolClient(this, 'VakUserPoolClient', {
          userPool,
          generateSecret: true,
          oAuth: {
            flows: { authorizationCodeGrant: true },
            scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
            callbackUrls: [`https://${props.domainName}/oauth2/idpresponse`],
            logoutUrls: [`https://${props.domainName}/logout`],
          },
          supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
        });
        const userPoolDomain = userPool.addDomain('VakUserPoolDomain', {
          cognitoDomain: { domainPrefix: props.cognitoDomainPrefix },
        });

        // onUnauthenticatedRequest=ALLOW: browsers with a valid Cognito cookie
        // get the full auth flow; API callers (Bearer token, WebSocket
        // access_token) pass through and FastAPI handles auth itself.
        for (const [suffix, pathPattern, priority] of [['Ws', '/ws*', 5], ['Chat', '/chat*', 6]] as const) {
          httpsListener.addAction(`Authenticate${suffix}`, {
            priority,
            conditions: [
              elbv2.ListenerCondition.pathPatterns([pathPattern]),
              elbv2.ListenerCondition.hostHeaders([props.domainName]),
            ],
            action: new elbv2Actions.AuthenticateCognitoAction({
              userPool,
              userPoolClient,
              userPoolDomain,
              onUnauthenticatedRequest: elbv2.UnauthenticatedAction.ALLOW,
              next: elbv2.ListenerAction.forward([targetGroup]),
            }),
          });
        }
      }

      if (props.domainName && hostedZone) {
        new route53.ARecord(this, 'ApiDnsRecord', {
          zone: hostedZone,
          recordName: props.domainName,
          target: route53.RecordTarget.fromAlias(new route53Targets.LoadBalancerTarget(alb)),
        });
      }
    }

    // ─── WAF (optional) ──────────────────────────────────────────────────────
    const webAclRules: wafv2.CfnWebACL.RuleProperty[] = [];

    if (props.enableTwilioOnlyAccess) {
      // Twilio Media Streams source IP ranges — see
      // https://www.twilio.com/docs/sip-trunking/ip-addresses for updates.
      const twilioIpRanges = [
        '54.172.60.0/22', '54.244.51.0/24', '54.171.127.192/26',
        '54.173.34.0/24', '54.235.223.0/24', '54.236.1.0/24',
        '54.236.2.0/24', '54.236.3.0/24', '54.236.4.0/24', '54.236.5.0/24',
        '54.236.6.0/24', '54.236.7.0/24', '54.236.8.0/24', '54.236.9.0/24',
        '54.236.10.0/24', '54.236.11.0/24', '54.236.12.0/24', '54.236.13.0/24',
        '54.236.14.0/24', '54.236.15.0/24', '54.236.16.0/24', '54.236.17.0/24',
        '54.236.18.0/24', '54.236.19.0/24', '54.236.20.0/24', '54.236.21.0/24',
        '54.236.22.0/24', '54.236.23.0/24', '54.236.24.0/24', '54.236.25.0/24',
        '54.236.26.0/24', '54.236.27.0/24', '54.236.28.0/24', '54.236.29.0/24',
        '54.236.30.0/24', '54.236.31.0/24',
      ];
      const twilioIpSet = new wafv2.CfnIPSet(this, 'TwilioIpSet', {
        name: `vak-twilio-ips-${stage}`,
        description: 'Twilio IP ranges for Media Streams',
        scope: 'REGIONAL',
        ipAddressVersion: 'IPV4',
        addresses: twilioIpRanges,
      });
      webAclRules.push({
        name: 'AllowTwilioIPs',
        priority: 1,
        statement: { ipSetReferenceStatement: { arn: twilioIpSet.attrArn } },
        action: { allow: {} },
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `AllowTwilioIPs-${stage}`,
        },
      });
    }

    if (props.apiKey) {
      // Requires an X-Api-Key header on every request except /health.
      webAclRules.push({
        name: 'AllowHealthCheck',
        priority: 0,
        statement: {
          byteMatchStatement: {
            searchString: '/health',
            fieldToMatch: { uriPath: {} },
            textTransformations: [{ priority: 0, type: 'NONE' }],
            positionalConstraint: 'STARTS_WITH',
          },
        },
        action: { allow: {} },
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `AllowHealthCheck-${stage}`,
        },
      });
      webAclRules.push({
        name: 'RequireApiKey',
        priority: 2,
        statement: {
          byteMatchStatement: {
            searchString: props.apiKey,
            fieldToMatch: { singleHeader: { name: 'x-api-key' } },
            textTransformations: [{ priority: 0, type: 'NONE' }],
            positionalConstraint: 'EXACTLY',
          },
        },
        action: { allow: {} },
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `RequireApiKey-${stage}`,
        },
      });
    }

    if (webAclRules.length > 0) {
      const webAcl = new wafv2.CfnWebACL(this, 'VakWebAcl', {
        name: `vak-web-acl-${stage}`,
        description: `Vak ALB protection (${stage})`,
        scope: 'REGIONAL',
        defaultAction: props.apiKey ? { block: {} } : { allow: {} },
        rules: webAclRules,
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `VakWebAcl-${stage}`,
        },
      });
      new wafv2.CfnWebACLAssociation(this, 'AlbWebAclAssociation', {
        resourceArn: alb.loadBalancerArn,
        webAclArn: webAcl.attrArn,
      });
    }

    // ─── Outputs ──────────────────────────────────────────────────────────────
    const scheme = certificate ? 'https' : 'http';
    const wsScheme = certificate ? 'wss' : 'ws';
    const host = props.domainName ?? alb.loadBalancerDnsName;

    new cdk.CfnOutput(this, 'ApiUrl', { value: `${scheme}://${host}`, description: 'VakDeepGram API URL' });
    new cdk.CfnOutput(this, 'WebSocketUrl', { value: `${wsScheme}://${host}/ws`, description: 'WebSocket URL for VakClient (VITE_WS_URL)' });
    new cdk.CfnOutput(this, 'AlbDns', { value: alb.loadBalancerDnsName, description: 'ALB DNS name' });
    new cdk.CfnOutput(this, 'EcsCluster', { value: cluster.clusterName, description: 'ECS cluster name' });
    new cdk.CfnOutput(this, 'EcrRepositoryUri', { value: deepgramEcrRepo.repositoryUri, description: 'Push images here, tagged as imageTag' });
  }
}
