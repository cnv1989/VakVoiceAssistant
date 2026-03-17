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
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as route53Targets from 'aws-cdk-lib/aws-route53-targets';
import { Construct } from 'constructs';
import { VakNetworkStack } from './vak-network-stack';

export interface VakAppStackProps extends cdk.StackProps {
  networkStack: VakNetworkStack;

  /** Deployment stage: 'alpha' | 'beta' | 'prod' */
  stage: string;

  /**
   * Amplify Gen 2 environment ID embedded in DynamoDB table names.
   * Format: <ModelName>-<amplifyEnvId>-NONE
   * For prod: 'pxy5meaaojbaxjwedt6v6oidw4'
   * For alpha/beta: discover after first Amplify branch deploy via
   *   aws dynamodb list-tables | grep BusinessNumber
   * Then update cdk.json stages.<stage>.amplifyEnvId.
   */
  amplifyEnvId: string;

  /**
   * Custom domain for this stage's VakDeepGram API.
   * e.g. 'api.groommate.ai' | 'beta-api.groommate.ai' | 'alpha-api.groommate.ai'
   * A Route53 A alias record is created pointing to the ALB.
   */
  apiDomain: string;

  /** Route53 hosted zone for groommate.ai (from VakDnsStack). */
  hostedZone: route53.IHostedZone;

  /**
   * ACM certificate ARN covering *.groommate.ai (from VakDnsStack).
   * Used for the HTTPS/WSS ALB listener.
   */
  certificateArn: string;

  /** Deepgram API key secret ARN from Secrets Manager. */
  deepgramApiKeySecretArn?: string;
  /** Fallback Deepgram API key (deprecated). */
  deepgramApiKey?: string;

  /** Twilio auth token secret ARN from Secrets Manager. */
  twilioAuthTokenSecretArn?: string;
  /** Fallback Twilio auth token (deprecated). */
  twilioAuthToken?: string;

  /** Enable WAF IP allowlist restricting ALB to Twilio IPs only. */
  enableTwilioOnlyAccess?: boolean;

  /**
   * Cognito hosted-UI domain prefix for ALB auth.
   * e.g. 'groommate-auth-prod' | 'groommate-auth-beta' | 'groommate-auth-alpha'
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

    const { stage, amplifyEnvId, apiDomain } = props;
    const { vpc, deepgramEcrRepo } = props.networkStack;

    // ─── Stage helpers ────────────────────────────────────────────────────────
    this.stage = stage;
    const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

    // ─── DynamoDB — Sessions table (owned by VakDeepGram) ────────────────────
    const sessionsTable = new dynamodb.Table(this, 'SessionsTable', {
      tableName: `Sessions-${cap(stage)}`,
      partitionKey: { name: 'sid', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.sessionsTable = sessionsTable;

    // ─── S3 Artifacts bucket ─────────────────────────────────────────────────
    const artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `vak-artifacts-${this.account}-${this.region}-${stage}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        {
          id: 'expire-call-sessions-30d',
          prefix: 'call-sessions/',
          expiration: cdk.Duration.days(30),
          enabled: true,
        },
      ],
    });
    this.artifactsBucket = artifactsBucket;

    // ─── ECS Cluster ─────────────────────────────────────────────────────────
    const cluster = new ecs.Cluster(this, 'VakCluster', {
      vpc,
      clusterName: `vak-cluster-${stage}`,
    });
    this.cluster = cluster;

    // ─── IAM roles ───────────────────────────────────────────────────────────
    const taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    let deepgramSecret: secretsmanager.ISecret | undefined;
    let twilioSecret: secretsmanager.ISecret | undefined;

    if (props.deepgramApiKeySecretArn) {
      deepgramSecret = secretsmanager.Secret.fromSecretCompleteArn(
        this, 'DeepgramSecret', props.deepgramApiKeySecretArn
      );
      deepgramSecret.grantRead(taskExecutionRole);
    }
    if (props.twilioAuthTokenSecretArn) {
      twilioSecret = secretsmanager.Secret.fromSecretCompleteArn(
        this, 'TwilioSecret', props.twilioAuthTokenSecretArn
      );
      twilioSecret.grantRead(taskExecutionRole);
    }

    this.taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    const taskRole = this.taskRole;

    // Sessions table (owned by this stack)
    sessionsTable.grantReadWriteData(taskRole);

    // S3 artifacts bucket — used for call transcripts and recordings
    artifactsBucket.grantReadWrite(taskRole);

    // Amplify-owned DynamoDB tables — grant access by ARN
    const amplifyTableArn = (model: string) =>
      `arn:aws:dynamodb:${this.region}:${this.account}:table/${model}-${amplifyEnvId}-NONE`;

    const amplifyTables = [
      'SquareAccount',
      'BusinessNumber',
      'SetmoreAccount',
      'BusinessAutomations',
      'CallRecord',
      'VoiceCustomer',
    ].map(model => dynamodb.Table.fromTableArn(this, `${model}Table`, amplifyTableArn(model)));

    amplifyTables.forEach(t => t.grantReadWriteData(taskRole));

    // Also grant GSI access for CallRecord (queried by businessNumber + dateStr)
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'dynamodb:Query',
        'dynamodb:Scan',
      ],
      resources: [
        `${amplifyTableArn('CallRecord')}/index/*`,
        `${amplifyTableArn('BusinessNumber')}/index/*`,
        `${amplifyTableArn('SetmoreAccount')}/index/*`,
        `${amplifyTableArn('VoiceCustomer')}/index/*`,
      ],
    }));

    // Bedrock for Strands Agent / chat endpoint
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/*`],
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

    // Stage-specific table names derived from amplifyEnvId
    const tableEnv = (model: string) => `${model}-${amplifyEnvId}-NONE`;

    const container = taskDefinition.addContainer('VakDeepGram', {
      // Each stage has its own image tag (alpha/beta/prod) in the shared ECR repo
      image: ecs.ContainerImage.fromEcrRepository(deepgramEcrRepo, stage),
      cpu: 512,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'vak-deepgram',
        logGroup: serviceLogGroup,
      }),
      environment: {
        HOST: '0.0.0.0',
        PORT: '8080',
        LOG_LEVEL: stage === 'prod' ? 'info' : 'debug',
        LOCAL_MODE: 'false',
        DEPLOY_STAGE: stage,

        // Deepgram configuration
        DEEPGRAM_AGENT_LANGUAGE: 'en',
        DEEPGRAM_LISTENING_MODEL: 'flux-general-en',
        DEEPGRAM_LISTENING_VERSION: 'v2',
        DEEPGRAM_THINKING_PROVIDER: 'google',
        DEEPGRAM_THINKING_MODEL: 'gemini-2.5-flash',
        DEEPGRAM_SPEAKING_PROVIDER: 'eleven_labs',
        DEEPGRAM_SPEAKING_MODEL_ID: 'eleven_flash_v2_5',
        DEEPGRAM_SPEAKING_VOICE_ID: 'cgSgspJ2msm6clMCkdW9',
        DEEPGRAM_INPUT_SAMPLE_RATE: '48000',
        DEEPGRAM_OUTPUT_SAMPLE_RATE: '24000',

        // Twilio configuration (non-sensitive)
        TWILIO_ACCOUNT_SID: 'ACd00787e66384ec2d2ed3e262748525af',
        TWILIO_FROM_NUMBER: '+18664766609',

        // S3 bucket for call transcripts and recordings
        RECORDINGS_BUCKET: artifactsBucket.bucketName,
        RECORDINGS_KEY_PREFIX: 'call-sessions',

        // DynamoDB table names (stage-specific via amplifyEnvId)
        BUSINESS_NUMBER_TABLE: tableEnv('BusinessNumber'),
        SQUARE_ACCOUNT_TABLE: tableEnv('SquareAccount'),
        SETMORE_ACCOUNT_TABLE: tableEnv('SetmoreAccount'),
        BUSINESS_AUTOMATIONS_TABLE: tableEnv('BusinessAutomations'),
        CALL_RECORD_TABLE: tableEnv('CallRecord'),
        VOICE_CUSTOMER_TABLE: tableEnv('VoiceCustomer'),

        // Service URL for this stage
        ALB_DNS: apiDomain,

        // API key for /chat endpoint (used by Slack bot and other internal callers)
        CHAT_API_KEY: 'HZB8Yk-odYjZrEmyFEKZx-UMNCfKoRiBv0Oi2eeKiSg',
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
    if (!twilioSecret) container.addEnvironment('TWILIO_AUTH_TOKEN', props.twilioAuthToken || '');

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

    // ─── Target Group ────────────────────────────────────────────────────────
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

    // ─── HTTP Listener ───────────────────────────────────────────────────────
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

    // ─── HTTPS Listener + Cognito auth ───────────────────────────────────────
    const certificate = elbv2.ListenerCertificate.fromArn(props.certificateArn);
    const httpsListener = alb.addListener('VakHttpsListener', {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [certificate],
      defaultTargetGroups: [targetGroup],
    });

    if (props.cognitoDomainPrefix) {
      const userPool = new cognito.UserPool(this, 'VakUserPool', {
        selfSignUpEnabled: false,
        signInAliases: { email: true },
        userInvitation: {
          emailSubject: 'You are invited to Vak',
          emailBody: 'Your username is {username} and temporary password is {####}.',
        },
      });
      const callbackUrl = `https://${apiDomain}/oauth2/idpresponse`;
      const logoutUrl = `https://${apiDomain}/logout`;
      const userPoolClient = new cognito.UserPoolClient(this, 'VakUserPoolClient', {
        userPool,
        generateSecret: true,
        oAuth: {
          flows: { authorizationCodeGrant: true },
          scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
          callbackUrls: [callbackUrl],
          logoutUrls: [logoutUrl],
        },
        supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      });
      const userPoolDomain = userPool.addDomain('VakUserPoolDomain', {
        cognitoDomain: { domainPrefix: props.cognitoDomainPrefix },
      });

      // onUnauthenticatedRequest=ALLOW: browser sessions with a valid Cognito cookie
      // get the full auth flow; API callers (Bearer token, WebSocket access_token)
      // pass through directly to FastAPI which handles auth itself.
      httpsListener.addAction('AuthenticateWs', {
        priority: 5,
        conditions: [
          elbv2.ListenerCondition.pathPatterns(['/ws*']),
          elbv2.ListenerCondition.hostHeaders([apiDomain]),
        ],
        action: new elbv2Actions.AuthenticateCognitoAction({
          userPool,
          userPoolClient,
          userPoolDomain,
          onUnauthenticatedRequest: elbv2.UnauthenticatedAction.ALLOW,
          next: elbv2.ListenerAction.forward([targetGroup]),
        }),
      });
      httpsListener.addAction('AuthenticateChat', {
        priority: 6,
        conditions: [
          elbv2.ListenerCondition.pathPatterns(['/chat*']),
          elbv2.ListenerCondition.hostHeaders([apiDomain]),
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

    // ─── Route53 A record: apiDomain → ALB ───────────────────────────────────
    new route53.ARecord(this, 'ApiDnsRecord', {
      zone: props.hostedZone,
      recordName: apiDomain,
      target: route53.RecordTarget.fromAlias(new route53Targets.LoadBalancerTarget(alb)),
    });

    // ─── WAF (optional) ──────────────────────────────────────────────────────
    if (props.enableTwilioOnlyAccess) {
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
      const webAcl = new wafv2.CfnWebACL(this, 'TwilioOnlyWebAcl', {
        name: `vak-twilio-only-${stage}`,
        description: `WAF: allow Twilio IPs only (${stage})`,
        scope: 'REGIONAL',
        defaultAction: { block: {} },
        rules: [{
          name: 'AllowTwilioIPs',
          priority: 1,
          statement: { ipSetReferenceStatement: { arn: twilioIpSet.attrArn } },
          action: { allow: {} },
          visibilityConfig: {
            sampledRequestsEnabled: true,
            cloudWatchMetricsEnabled: true,
            metricName: `AllowTwilioIPs-${stage}`,
          },
        }],
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `TwilioOnlyWebAcl-${stage}`,
        },
      });
      new wafv2.CfnWebACLAssociation(this, 'AlbWebAclAssociation', {
        resourceArn: alb.loadBalancerArn,
        webAclArn: webAcl.attrArn,
      });
    }

    // ─── Outputs ──────────────────────────────────────────────────────────────
    const stageCap = cap(stage);

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: `https://${apiDomain}`,
      description: `VakDeepGram API URL (${stage})`,
      exportName: `VakApiUrl-${stageCap}`,
    });
    new cdk.CfnOutput(this, 'WebSocketSecureUrl', {
      value: `wss://${apiDomain}/ws`,
      description: `Secure WebSocket URL (${stage})`,
      exportName: `VakWebSocketSecureUrl-${stageCap}`,
    });
    new cdk.CfnOutput(this, 'AlbDns', {
      value: alb.loadBalancerDnsName,
      description: `ALB DNS name (${stage})`,
      exportName: `VakAlbDns-${stageCap}`,
    });
    new cdk.CfnOutput(this, 'EcsCluster', {
      value: cluster.clusterName,
      description: `ECS cluster name (${stage})`,
      exportName: `VakEcsCluster-${stageCap}`,
    });
    new cdk.CfnOutput(this, 'SessionsTableName', {
      value: sessionsTable.tableName,
      description: `Sessions DynamoDB table (${stage})`,
      exportName: `VakSessionsTable-${stageCap}`,
    });
  }
}
