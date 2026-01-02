import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { VakNetworkStack } from './vak-network-stack';

export interface VakAppStackProps extends cdk.StackProps {
  networkStack: VakNetworkStack;
}

export class VakAppStack extends cdk.Stack {
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

    // S3 bucket for artifacts
    const artifactsBucket = new s3.Bucket(this, 'ArtifactsBucket', {
      bucketName: `vak-artifacts-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // ECS Cluster
    const cluster = new ecs.Cluster(this, 'VakCluster', {
      vpc,
      clusterName: 'vak-cluster',
    });

    // Task execution role
    const taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Task role - minimal permissions for Deepgram Voice Agents
    // Deepgram uses API key authentication, not AWS services
    const taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // No AWS service permissions needed - Deepgram uses external API
    // Keep S3 and DynamoDB grants if needed for other purposes, otherwise remove
    // artifactsBucket.grantReadWrite(taskRole);
    // sessionsTable.grantReadWriteData(taskRole);

    // ECS Task Definition
    // Valid Fargate CPU/Memory combinations: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'VakTaskDefinition', {
      memoryLimitMiB: 1024,  // 1 GB
      cpu: 512,              // 0.5 vCPU (valid combination with 1024 MB)
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    // Container definition using Deepgram ECR image
    // Image must be built and pushed to ECR manually before deployment
    // Use the Deepgram ECR repository from the network stack
    const container = taskDefinition.addContainer('VakDeepGram', {
      image: ecs.ContainerImage.fromEcrRepository(deepgramEcrRepo, 'latest'),
      cpu: 512,  // 0.5 vCPU (matching task definition CPU allocation)
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'vak-deepgram',
      }),
      environment: {
        HOST: '0.0.0.0',
        PORT: '8080',
        LOG_LEVEL: 'info',
        // Deepgram configuration
        DEEPGRAM_AGENT_LANGUAGE: 'en',
        DEEPGRAM_LISTENING_MODEL: 'flux-general-en',
        DEEPGRAM_LISTENING_VERSION: 'v2',
        DEEPGRAM_THINKING_PROVIDER: 'google',
        DEEPGRAM_THINKING_MODEL: 'gemini-2.5-flash',
        DEEPGRAM_SPEAKING_PROVIDER: 'eleven_labs',
        DEEPGRAM_SPEAKING_MODEL_ID: 'eleven_multilingual_v2',
        DEEPGRAM_SPEAKING_VOICE_ID: 'cgSgspJ2msm6clMCkdW9',
        DEEPGRAM_INPUT_SAMPLE_RATE: '48000',
        DEEPGRAM_OUTPUT_SAMPLE_RATE: '24000',
      },
      // Note: DEEPGRAM_API_KEY is required and should be provided via Secrets Manager
      // Example:
      // secrets: {
      //   DEEPGRAM_API_KEY: ecs.Secret.fromSecretsManager(secret, 'DEEPGRAM_API_KEY'),
      // }
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

    // Application Load Balancer
    // Internet-facing ALB for direct WebSocket connections with IAM authentication
    const alb = new elbv2.ApplicationLoadBalancer(this, 'VakAlb', {
      vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
    });

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

    service.attachToApplicationTargetGroup(targetGroup);

    // HTTP listener on port 80 for WebSocket connections
    // Note: ALB supports WebSocket connections over HTTP
    // For IAM authentication, we validate signatures in the application
    // ALB doesn't have native IAM auth actions for WebSocket, so we handle it at app level
    // In production, consider using HTTPS listener with ACM certificate
    const httpListener = alb.addListener('VakListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

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
      description: 'WebSocket endpoint URL (direct to ALB)',
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
