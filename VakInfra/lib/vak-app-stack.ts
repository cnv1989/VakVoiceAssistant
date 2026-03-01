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
import { Construct } from 'constructs';
import { VakNetworkStack } from './vak-network-stack';

export interface VakAppStackProps extends cdk.StackProps {
  networkStack: VakNetworkStack;
  /**
   * Optional Deepgram API key secret ARN from AWS Secrets Manager.
   * Secret should be stored as plaintext in Secrets Manager.
   * If not provided, falls back to deepgramApiKey prop or empty string.
   * Example: 'arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/deepgram-api-key-xxxxx'
   */
  deepgramApiKeySecretArn?: string;
  /**
   * Optional Deepgram API key (deprecated, use deepgramApiKeySecretArn instead).
   * Kept for backward compatibility.
   */
  deepgramApiKey?: string;
  /**
   * Optional Twilio auth token secret ARN from AWS Secrets Manager.
   * Secret should be stored as plaintext in Secrets Manager.
   * If not provided, falls back to twilioAuthToken prop or hardcoded value.
   * Example: 'arn:aws:secretsmanager:us-west-2:123456789012:secret:vak/twilio-auth-token-xxxxx'
   */
  twilioAuthTokenSecretArn?: string;
  /**
   * Optional Twilio auth token (deprecated, use twilioAuthTokenSecretArn instead).
   * Kept for backward compatibility.
   */
  twilioAuthToken?: string;
  /**
   * Optional ACM certificate ARN for HTTPS/WSS support.
   * If provided, an HTTPS listener will be added on port 443.
   * Certificate must be in the same region as the ALB (us-west-2).
   * Example: 'arn:aws:acm:us-west-2:123456789012:certificate/12345678-1234-1234-1234-123456789012'
   */
  certificateArn?: string;
  /**
   * Optional: Enable WAF protection to restrict access to Twilio IPs only.
   * If true, creates a WAF WebACL that only allows traffic from Twilio IP ranges.
   * Default: false (allow all traffic)
   */
  enableTwilioOnlyAccess?: boolean;
  /**
   * Hostname to protect with Cognito auth.
   */
  cognitoHost?: string;
  /**
   * Cognito hosted UI domain prefix (e.g. vak-auth).
   */
  cognitoDomainPrefix?: string;
}

export class VakAppStack extends cdk.Stack {
  public readonly cluster: ecs.Cluster;
  public readonly service: ecs.FargateService;
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly targetGroup: elbv2.ApplicationTargetGroup;
  public readonly sessionsTable: dynamodb.Table;
  public readonly artifactsBucket: s3.Bucket;
  public readonly serviceLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: VakAppStackProps) {
    super(scope, id, props);

    const { vpc, deepgramEcrRepo } = props.networkStack;

    // DynamoDB table for sessions
    const sessionsTable = new dynamodb.Table(this, 'SessionsTable', {
      tableName: 'Sessions',
      partitionKey: { name: 'sid', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.sessionsTable = sessionsTable;

    // S3 bucket for artifacts
    const artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `vak-artifacts-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });
    this.artifactsBucket = artifactsBucket;

    // ECS Cluster
    const cluster = new ecs.Cluster(this, 'VakCluster', {
      vpc,
      clusterName: 'vak-cluster',
    });
    this.cluster = cluster;

    // Task execution role
    const taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Create secret references from ARNs (if provided)
    let deepgramSecret: secretsmanager.ISecret | undefined;
    let twilioSecret: secretsmanager.ISecret | undefined;

    if (props.deepgramApiKeySecretArn) {
      deepgramSecret = secretsmanager.Secret.fromSecretCompleteArn(
        this,
        'DeepgramSecret',
        props.deepgramApiKeySecretArn
      );
      // Grant task execution role permission to read the secret
      deepgramSecret.grantRead(taskExecutionRole);
    }

    if (props.twilioAuthTokenSecretArn) {
      twilioSecret = secretsmanager.Secret.fromSecretCompleteArn(
        this,
        'TwilioSecret',
        props.twilioAuthTokenSecretArn
      );
      // Grant task execution role permission to read the secret
      twilioSecret.grantRead(taskExecutionRole);
    }


    // Task role - minimal permissions for Deepgram Voice Agents
    // Deepgram uses API key authentication, not AWS services
    const taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Allow ECS tasks to access DynamoDB sessions table.
    sessionsTable.grantReadWriteData(taskRole);
    const squareAccountTableArn = `arn:aws:dynamodb:${this.region}:${this.account}:table/SquareAccount-pxy5meaaojbaxjwedt6v6oidw4-NONE`;
    const businessNumberTableArn = `arn:aws:dynamodb:${this.region}:${this.account}:table/BusinessNumber-pxy5meaaojbaxjwedt6v6oidw4-NONE`;
    const setmoreAccountTableArn = `arn:aws:dynamodb:${this.region}:${this.account}:table/SetmoreAccount-pxy5meaaojbaxjwedt6v6oidw4-NONE`;
    const squareAccountTable = dynamodb.Table.fromTableArn(this, 'SquareAccountTable', squareAccountTableArn);
    const businessNumberTable = dynamodb.Table.fromTableArn(this, 'BusinessNumberTable', businessNumberTableArn);
    const setmoreAccountTable = dynamodb.Table.fromTableArn(this, 'SetmoreAccountTable', setmoreAccountTableArn);
    squareAccountTable.grantReadWriteData(taskRole);
    businessNumberTable.grantReadWriteData(taskRole);
    setmoreAccountTable.grantReadWriteData(taskRole);

    // Allow ECS tasks to invoke Bedrock models (for Strands Agent / chat endpoint)
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
      ],
      resources: [
        `arn:aws:bedrock:${this.region}::foundation-model/*`,
      ],
    }));

    // ECS Task Definition
    // Valid Fargate CPU/Memory combinations: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'VakTaskDefinition', {
      memoryLimitMiB: 1024,  // 1 GB
      cpu: 512,              // 0.5 vCPU (valid combination with 1024 MB)
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    const serviceLogGroup = new logs.LogGroup(this, 'VakServiceLogGroup', {
      logGroupName: '/ecs/vak-service',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.serviceLogGroup = serviceLogGroup;

    // Build secrets object conditionally
    const containerSecrets: { [key: string]: ecs.Secret } = {};
    if (deepgramSecret) {
      containerSecrets.DEEPGRAM_API_KEY = ecs.Secret.fromSecretsManager(deepgramSecret);
    }
    if (twilioSecret) {
      containerSecrets.TWILIO_AUTH_TOKEN = ecs.Secret.fromSecretsManager(twilioSecret);
    }

    // Container definition using Deepgram ECR image
    // Image must be built and pushed to ECR manually before deployment
    // Use the Deepgram ECR repository from the network stack
    const container = taskDefinition.addContainer('VakDeepGram', {
      image: ecs.ContainerImage.fromEcrRepository(deepgramEcrRepo, 'latest'),
      cpu: 512,  // 0.5 vCPU (matching task definition CPU allocation)
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'vak-deepgram',
        logGroup: serviceLogGroup,
      }),
      environment: {
        HOST: '0.0.0.0',
        PORT: '8080',
        LOG_LEVEL: 'info',
        // Deepgram configuration
        DEEPGRAM_AGENT_LANGUAGE: 'en',
        DEEPGRAM_LISTENING_MODEL: 'flux-general-en',
        DEEPGRAM_LISTENING_VERSION: 'v2',
        DEEPGRAM_THINKING_PROVIDER: 'open_ai',
        DEEPGRAM_THINKING_MODEL: 'gpt-5.2-instant',
        DEEPGRAM_SPEAKING_PROVIDER: 'eleven_labs',
        DEEPGRAM_SPEAKING_MODEL_ID: 'eleven_multilingual_v2',
        DEEPGRAM_SPEAKING_VOICE_ID: '0mevMNFMwHxBOUTpeMGN',
        DEEPGRAM_INPUT_SAMPLE_RATE: '48000',
        DEEPGRAM_OUTPUT_SAMPLE_RATE: '24000',
        // Twilio configuration (Account SID is not sensitive, only Auth Token is)
        TWILIO_ACCOUNT_SID: 'ACd00787e66384ec2d2ed3e262748525af',
      },
      secrets: Object.keys(containerSecrets).length > 0 ? containerSecrets : undefined,
      healthCheck: {
        command: [
          'CMD-SHELL',
          'curl -f http://localhost:8080/health || exit 1'
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60), // Grace period for container startup
      },
    });

    // Fallback: If secrets are not provided, use environment variables or hardcoded values
    // This maintains backward compatibility
    if (!deepgramSecret) {
      container.addEnvironment('DEEPGRAM_API_KEY', props.deepgramApiKey || '');
    }

    if (!twilioSecret) {
      container.addEnvironment('TWILIO_AUTH_TOKEN', props.twilioAuthToken || '203d5f5968243a3b4bc09da73e7b998c');
    }

    container.addPortMappings({
      containerPort: 8080,
      protocol: ecs.Protocol.TCP,
    });

    // ECS Service
    const service = new ecs.FargateService(this, 'VakService', {
      cluster,
      taskDefinition,
      desiredCount: 1,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      },
      healthCheckGracePeriod: cdk.Duration.seconds(60), // Grace period before health checks start counting failures
    });
    this.service = service;

    // Application Load Balancer
    // Internet-facing ALB for direct WebSocket connections with IAM authentication
    const alb = new elbv2.ApplicationLoadBalancer(this, 'VakAlb', {
      vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
    });
    this.alb = alb;

    // Configure ALB attributes for WebSocket support
    // Disable HTTP/2 (WebSocket upgrades require HTTP/1.1)
    // Increase idle timeout for long-lived WebSocket connections
    const cfnAlb = alb.node.defaultChild as elbv2.CfnLoadBalancer;
    cfnAlb.loadBalancerAttributes = [
      {
        key: 'routing.http2.enabled',
        value: 'false',
      },
      {
        key: 'idle_timeout.timeout_seconds',
        value: '3600', // 1 hour for WebSocket connections
      },
    ];

    // Target Group
    // For Fargate tasks with awsvpc network mode, targetType must be 'ip'
    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'VakTargetGroup', {
      vpc,
      port: 8080, 
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP, // Required for Fargate with awsvpc network mode
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

    const cognitoConfigured = Boolean(props.cognitoHost && props.cognitoDomainPrefix);

    if (cognitoConfigured && !props.certificateArn) {
      throw new Error('Cognito auth on /ws requires an HTTPS listener (certificateArn is missing).');
    }

    // HTTP listener on port 80 for WebSocket connections
    // Note: ALB supports WebSocket connections over HTTP
    // Keep the same logical ID 'VakListener' to update existing listener
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

    // Block /chat over HTTP - require HTTPS for Cognito auth
    httpListener.addAction('BlockChatOverHttp', {
      priority: 6,
      conditions: [elbv2.ListenerCondition.pathPatterns(['/chat*'])],
      action: elbv2.ListenerAction.fixedResponse(403, {
        contentType: 'text/plain',
        messageBody: 'Chat requires HTTPS. Use https://<host>/chat.',
      }),
    });

    // HTTPS listener on port 443 for secure WebSocket (WSS) connections
    // Only added if certificate ARN is provided
    if (props.certificateArn) {
      const certificate = elbv2.ListenerCertificate.fromArn(props.certificateArn);
      const httpsListener = alb.addListener('VakHttpsListener', {
        port: 443,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [certificate],
        defaultTargetGroups: [targetGroup],
      });

      if (cognitoConfigured) {
        const userPool = new cognito.UserPool(this, 'VakUserPool', {
          selfSignUpEnabled: false,
          signInAliases: { email: true },
          userInvitation: {
            emailSubject: 'You are invited to Vak',
            emailBody: 'Your username is {username} and temporary password is {####}.',
          },
        });
        const callbackUrl = `https://${props.cognitoHost}/oauth2/idpresponse`;
        const logoutUrl = `https://${props.cognitoHost}/logout`;
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
          cognitoDomain: { domainPrefix: props.cognitoDomainPrefix! },
        });

        httpsListener.addAction('AuthenticateWs', {
          priority: 5,
          conditions: [
            elbv2.ListenerCondition.pathPatterns(['/ws*']),
            elbv2.ListenerCondition.hostHeaders([props.cognitoHost!]),
          ],
          action: new elbv2Actions.AuthenticateCognitoAction({
            userPool,
            userPoolClient,
            userPoolDomain,
            next: elbv2.ListenerAction.forward([targetGroup]),
          }),
        });

        // Add Cognito auth for /chat endpoint (similar to /ws)
        httpsListener.addAction('AuthenticateChat', {
          priority: 6,
          conditions: [
            elbv2.ListenerCondition.pathPatterns(['/chat*']),
            elbv2.ListenerCondition.hostHeaders([props.cognitoHost!]),
          ],
          action: new elbv2Actions.AuthenticateCognitoAction({
            userPool,
            userPoolClient,
            userPoolDomain,
            next: elbv2.ListenerAction.forward([targetGroup]),
          }),
        });
      }

      // Output secure WebSocket URL
      new cdk.CfnOutput(this, 'WebSocketSecureUrl', {
        value: `wss://${alb.loadBalancerDnsName}/ws`,
        description: 'Secure WebSocket endpoint URL (WSS)',
        exportName: 'VakWebSocketSecureUrl',
      });
    }

    // WAF Protection: Restrict access to Twilio IPs only (if enabled)
    if (props.enableTwilioOnlyAccess) {
      // Twilio IP ranges (as of 2024)
      // Source: https://www.twilio.com/docs/voice/ip-addresses
      // Note: These IPs may change - update periodically via AWS Console or CDK
      const twilioIpRanges = [
        // Twilio Voice IPs (US)
        '54.172.60.0/22',
        '54.244.51.0/24',
        '54.171.127.192/26',
        '54.173.34.0/24',
        '54.235.223.0/24',
        '54.236.1.0/24',
        '54.236.2.0/24',
        '54.236.3.0/24',
        '54.236.4.0/24',
        '54.236.5.0/24',
        '54.236.6.0/24',
        '54.236.7.0/24',
        '54.236.8.0/24',
        '54.236.9.0/24',
        '54.236.10.0/24',
        '54.236.11.0/24',
        '54.236.12.0/24',
        '54.236.13.0/24',
        '54.236.14.0/24',
        '54.236.15.0/24',
        '54.236.16.0/24',
        '54.236.17.0/24',
        '54.236.18.0/24',
        '54.236.19.0/24',
        '54.236.20.0/24',
        '54.236.21.0/24',
        '54.236.22.0/24',
        '54.236.23.0/24',
        '54.236.24.0/24',
        '54.236.25.0/24',
        '54.236.26.0/24',
        '54.236.27.0/24',
        '54.236.28.0/24',
        '54.236.29.0/24',
        '54.236.30.0/24',
        '54.236.31.0/24',
        // Additional Twilio IPs
        '54.172.60.0/22',
        '54.244.51.0/24',
        '54.171.127.192/26',
        '54.173.34.0/24',
        '54.235.223.0/24',
      ];

      // Create IP Set for Twilio IPs
      const twilioIpSet = new wafv2.CfnIPSet(this, 'TwilioIpSet', {
        name: `vak-twilio-ips-${this.stackName}`,
        description: 'Twilio IP ranges for Media Streams',
        scope: 'REGIONAL', // Must be REGIONAL for ALB
        ipAddressVersion: 'IPV4',
        addresses: twilioIpRanges,
      });

      // Create WAF WebACL with IP allowlist rule
      // Default action: BLOCK all traffic
      // Rule: ALLOW only Twilio IPs
      const webAcl = new wafv2.CfnWebACL(this, 'TwilioOnlyWebAcl', {
        name: `vak-twilio-only-${this.stackName}`,
        description: 'WAF WebACL to restrict access to Twilio IPs only',
        scope: 'REGIONAL', // Must be REGIONAL for ALB
        defaultAction: {
          block: {}, // Block all traffic by default
        },
        rules: [
          {
            name: 'AllowTwilioIPs',
            priority: 1,
            statement: {
              ipSetReferenceStatement: {
                arn: twilioIpSet.attrArn,
              },
            },
            action: {
              allow: {}, // Allow traffic from Twilio IPs
            },
            visibilityConfig: {
              sampledRequestsEnabled: true,
              cloudWatchMetricsEnabled: true,
              metricName: 'AllowTwilioIPs',
            },
          },
        ],
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: 'TwilioOnlyWebAcl',
        },
      });

      // Associate WebACL with ALB
      new wafv2.CfnWebACLAssociation(this, 'AlbWebAclAssociation', {
        resourceArn: alb.loadBalancerArn,
        webAclArn: webAcl.attrArn,
      });

      // Output WAF ARN
      new cdk.CfnOutput(this, 'WebAclArn', {
        value: webAcl.attrArn,
        description: 'WAF WebACL ARN (Twilio IP allowlist)',
        exportName: 'VakWebAclArn',
      });

      new cdk.CfnOutput(this, 'IpSetArn', {
        value: twilioIpSet.attrArn,
        description: 'Twilio IP Set ARN',
        exportName: 'VakTwilioIpSetArn',
      });
    }

    // IAM policy for clients to connect to ALB
    // Clients will sign WebSocket upgrade requests with AWS credentials
    // The server will validate these signatures
    const albAccessPolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['elasticloadbalancing:DescribeLoadBalancers'],
          resources: ['*'],
        }),
      ],
    });

    // Update container environment - no longer using API Gateway
    // Server will handle WebSocket connections directly
    container.addEnvironment('LOCAL_MODE', 'false');
    container.addEnvironment('ALB_DNS', alb.loadBalancerDnsName);

    // Outputs
    new cdk.CfnOutput(this, 'WebSocketUrl', {
      value: `ws://${alb.loadBalancerDnsName}/ws`,
      description: 'WebSocket endpoint URL (HTTP, direct to ALB)',
      exportName: 'VakWebSocketUrl',
    });

    new cdk.CfnOutput(this, 'AlbDns', {
      value: alb.loadBalancerDnsName,
      description: 'Application Load Balancer DNS name',
      exportName: 'VakAlbDns',
    });

    new cdk.CfnOutput(this, 'AlbArn', {
      value: alb.loadBalancerArn,
      description: 'Application Load Balancer ARN (for IAM policies)',
      exportName: 'VakAlbArn',
    });

    new cdk.CfnOutput(this, 'DynamoDbTableName', {
      value: sessionsTable.tableName,
      description: 'DynamoDB Sessions table name',
      exportName: 'VakDynamoDbTableName',
    });

    new cdk.CfnOutput(this, 'S3BucketName', {
      value: artifactsBucket.bucketName,
      description: 'S3 Artifacts bucket name',
      exportName: 'VakS3BucketName',
    });
  }
}
