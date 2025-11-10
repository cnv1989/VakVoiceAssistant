import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as apigatewayv2 from 'aws-cdk-lib/aws-apigatewayv2';
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

    const { vpc, ecrRepo } = props.networkStack;

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

    // Task role with permissions for Bedrock, Transcribe, Polly, S3, DynamoDB
    const taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: ['*'],
      })
    );

    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'transcribe:StartStreamTranscription',
        ],
        resources: ['*'],
      })
    );

    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'polly:SynthesizeSpeech',
        ],
        resources: ['*'],
      })
    );

    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'execute-api:ManageConnections',
        ],
        resources: ['*'],
      })
    );

    artifactsBucket.grantReadWrite(taskRole);
    sessionsTable.grantReadWriteData(taskRole);

    // ECS Task Definition
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'VakTaskDefinition', {
      memoryLimitMiB: 512,
      cpu: 256,
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    // Container definition using ECR image
    // Image must be built and pushed to ECR manually before deployment
    // Use the ECR repository from the network stack
    const container = taskDefinition.addContainer('VakServer', {
      image: ecs.ContainerImage.fromEcrRepository(ecrRepo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'vak-server',
      }),
      environment: {
        REGION: this.region,
        BUCKET: artifactsBucket.bucketName,
        DDB_TABLE: sessionsTable.tableName,
        MODEL_ID: 'anthropic.claude-3-haiku-20240307-v1:0',
        POLLY_VOICE: 'Joanna',
      },
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

    // Network Load Balancer
    // Made internet-facing so WebSocket API can reach it (WebSocket APIs don't support VPC Links)
    // VPC Endpoint Service is still available for other VPC consumers
    const nlb = new elbv2.NetworkLoadBalancer(this, 'VakNlb', {
      vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
    });

    // Target Group
    // For Fargate tasks with awsvpc network mode, targetType must be 'ip'
    const targetGroup = new elbv2.NetworkTargetGroup(this, 'VakTargetGroup', {
      vpc,
      port: 8080,
      protocol: elbv2.Protocol.TCP,
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

    service.attachToNetworkTargetGroup(targetGroup);

    nlb.addListener('VakListener', {
      port: 80,
      protocol: elbv2.Protocol.TCP,
      defaultTargetGroups: [targetGroup],
    });

    // VPC Endpoint Service for NLB
    const vpcEndpointService = new ec2.VpcEndpointService(this, 'VakVpcEndpointService', {
      vpcEndpointServiceLoadBalancers: [nlb],
      acceptanceRequired: false,
    });

    // IAM role for API Gateway to sign requests to NLB with SigV4
    const apiGatewayIntegrationRole = new iam.Role(this, 'ApiGatewayIntegrationRole', {
      assumedBy: new iam.ServicePrincipal('apigateway.amazonaws.com'),
      description: 'Role for API Gateway to invoke NLB with IAM authentication',
    });

    // WebSocket API with HTTP integrations to NLB
    // Note: WebSocket APIs don't support VPC Links, so NLB must be internet-facing
    // The VPC Endpoint Service is still available for other VPC consumers
    const nlbDnsName = nlb.loadBalancerDnsName;
    
    // Create WebSocket API first
    const wsApi = new apigatewayv2.WebSocketApi(this, 'VakWebSocketApi', {
      apiName: 'vak-websocket-api',
    });

    // Create HTTP integrations for WebSocket API routes
    // Note: WebSocket APIs support HTTP integration type (not AWS) for HTTP backends
    const connectIntegration = new apigatewayv2.CfnIntegration(this, 'ConnectIntegration', {
      apiId: wsApi.apiId,
      integrationType: 'HTTP',
      integrationUri: `http://${nlbDnsName}/connect`,
      integrationMethod: 'POST',
      requestTemplates: {
        'application/json': JSON.stringify({
          connectionId: '$context.connectionId',
          body: '$input.body',
        }),
      },
    });

    const disconnectIntegration = new apigatewayv2.CfnIntegration(this, 'DisconnectIntegration', {
      apiId: wsApi.apiId,
      integrationType: 'HTTP',
      integrationUri: `http://${nlbDnsName}/disconnect`,
      integrationMethod: 'POST',
      requestTemplates: {
        'application/json': JSON.stringify({
          connectionId: '$context.connectionId',
          body: '$input.body',
        }),
      },
    });

    const defaultIntegration = new apigatewayv2.CfnIntegration(this, 'DefaultIntegration', {
      apiId: wsApi.apiId,
      integrationType: 'HTTP',
      integrationUri: `http://${nlbDnsName}/default`,
      integrationMethod: 'POST',
      requestTemplates: {
        'application/json': JSON.stringify({
          connectionId: '$context.connectionId',
          body: '$input.body',
        }),
      },
    });

    // Create routes using CfnRoute to reference the HTTP integrations
    // Note: IAM authorization can only be applied to $connect route
    new apigatewayv2.CfnRoute(this, 'ConnectRoute', {
      apiId: wsApi.apiId,
      routeKey: '$connect',
      target: `integrations/${connectIntegration.ref}`,
      authorizationType: 'AWS_IAM',
    });

    new apigatewayv2.CfnRoute(this, 'DisconnectRoute', {
      apiId: wsApi.apiId,
      routeKey: '$disconnect',
      target: `integrations/${disconnectIntegration.ref}`,
    });

    new apigatewayv2.CfnRoute(this, 'DefaultRoute', {
      apiId: wsApi.apiId,
      routeKey: '$default',
      target: `integrations/${defaultIntegration.ref}`,
    });

    // WebSocket Stage (needed for endpoint URL)
    const wsStage = new apigatewayv2.WebSocketStage(this, 'VakWebSocketStage', {
      webSocketApi: wsApi,
      stageName: 'prod',
      autoDeploy: true,
    });

    // Update container environment with WS_API_ENDPOINT and API_GATEWAY_API_ID
    container.addEnvironment('WS_API_ENDPOINT', 
      `https://${wsApi.apiId}.execute-api.${this.region}.amazonaws.com/${wsStage.stageName}`
    );
    container.addEnvironment('API_GATEWAY_API_ID', wsApi.apiId);

    // Outputs
    new cdk.CfnOutput(this, 'WebSocketUrl', {
      value: wsApi.apiEndpoint,
      description: 'WebSocket API endpoint URL',
      exportName: 'VakWebSocketUrl',
    });

    new cdk.CfnOutput(this, 'NlbDns', {
      value: nlb.loadBalancerDnsName,
      description: 'Network Load Balancer DNS name',
      exportName: 'VakNlbDns',
    });

    new cdk.CfnOutput(this, 'VpcEndpointServiceName', {
      value: vpcEndpointService.vpcEndpointServiceName,
      description: 'VPC Endpoint Service name for NLB',
      exportName: 'VakVpcEndpointServiceName',
    });

    new cdk.CfnOutput(this, 'WsApiEndpoint', {
      value: `https://${wsApi.apiId}.execute-api.${this.region}.amazonaws.com/${wsStage.stageName}`,
      description: 'WebSocket API HTTP endpoint for ApiGatewayManagementApi',
      exportName: 'VakWsApiEndpoint',
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
