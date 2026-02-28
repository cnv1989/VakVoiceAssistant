import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';
import { VakAppStack } from './vak-app-stack';

export interface VakMonitoringStackProps extends cdk.StackProps {
  appStack: VakAppStack;
}

export class VakMonitoringStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: VakMonitoringStackProps) {
    super(scope, id, props);

    const { appStack } = props;

    const service = appStack.service;
    const alb = appStack.alb;
    const targetGroup = appStack.targetGroup;
    const sessionsTable = appStack.sessionsTable;
    const artifactsBucket = appStack.artifactsBucket;
    const serviceLogGroup = appStack.serviceLogGroup;

    const period = cdk.Duration.minutes(5);

    const cpuUtilization = service.metricCpuUtilization({ period });
    const memoryUtilization = service.metricMemoryUtilization({ period });
    const runningTasks = new cloudwatch.Metric({
      namespace: 'AWS/ECS',
      metricName: 'RunningTaskCount',
      dimensionsMap: {
        ClusterName: service.cluster.clusterName,
        ServiceName: service.serviceName,
      },
      statistic: 'Average',
      period,
    });
    const desiredTasks = new cloudwatch.Metric({
      namespace: 'AWS/ECS',
      metricName: 'DesiredTaskCount',
      dimensionsMap: {
        ClusterName: service.cluster.clusterName,
        ServiceName: service.serviceName,
      },
      statistic: 'Average',
      period,
    });

    const runningLessThanDesired = new cloudwatch.MathExpression({
      expression: 'running < desired',
      usingMetrics: {
        running: runningTasks,
        desired: desiredTasks,
      },
      period,
      label: 'Running < Desired',
    });

    const albRequestCount = alb.metrics.requestCount({ period, statistic: 'Sum' });
    const albTargetResponseTimeP90 = alb.metrics.targetResponseTime({ period, statistic: 'p90' });
    const albHttp5xx = alb.metrics.httpCodeTarget(elbCode('5xx'), { period, statistic: 'Sum' });
    const albHttp4xx = alb.metrics.httpCodeTarget(elbCode('4xx'), { period, statistic: 'Sum' });

    const healthyHosts = targetGroup.metricHealthyHostCount({ period });
    const unhealthyHosts = targetGroup.metricUnhealthyHostCount({ period });

    const ddbThrottles = sessionsTable.metricThrottledRequests({ period, statistic: 'Sum' });
    const ddbConsumedRead = sessionsTable.metricConsumedReadCapacityUnits({ period });
    const ddbConsumedWrite = sessionsTable.metricConsumedWriteCapacityUnits({ period });

    const s3BucketSize = new cloudwatch.Metric({
      namespace: 'AWS/S3',
      metricName: 'BucketSizeBytes',
      dimensionsMap: {
        BucketName: artifactsBucket.bucketName,
        StorageType: 'StandardStorage',
      },
      statistic: 'Average',
      period,
    });
    const s3Requests = new cloudwatch.Metric({
      namespace: 'AWS/S3',
      metricName: 'NumberOfObjects',
      dimensionsMap: {
        BucketName: artifactsBucket.bucketName,
        StorageType: 'AllStorageTypes',
      },
      statistic: 'Average',
      period,
    });

    const errorFilter = new logs.MetricFilter(this, 'VakServiceErrorFilter', {
      logGroup: serviceLogGroup,
      metricNamespace: 'VakDeepGram',
      metricName: 'ErrorCount',
      filterPattern: logs.FilterPattern.anyTerm('ERROR', 'Error', 'Exception', 'Traceback'),
      metricValue: '1',
    });

    const errorMetric = errorFilter.metric({
      period,
      statistic: 'Sum',
    });

    const toolErrorSearch = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,ToolCallErrorCount} MetricName=\"ToolCallErrorCount\"', 'Sum', 300)",
      period,
      label: 'Tool errors (all)',
    });

    const toolLatencyP95 = new cloudwatch.MathExpression({
      expression: "MAX(SEARCH('{VakDeepGram,ToolCallLatencyMs} MetricName=\"ToolCallLatencyMs\"', 'p95', 300))",
      period,
      label: 'Tool latency p95 (max)',
    });

    const agentErrorChatSquare = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentInvokeErrorCount',
      dimensionsMap: { endpoint: 'chat', provider: 'square' },
      statistic: 'Sum',
      period,
    });
    const agentErrorChatSetmore = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentInvokeErrorCount',
      dimensionsMap: { endpoint: 'chat', provider: 'setmore' },
      statistic: 'Sum',
      period,
    });
    const agentErrorTwilioSquare = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentInvokeErrorCount',
      dimensionsMap: { endpoint: 'twilio_chat', provider: 'square' },
      statistic: 'Sum',
      period,
    });
    const agentErrorTwilioSetmore = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentInvokeErrorCount',
      dimensionsMap: { endpoint: 'twilio_chat', provider: 'setmore' },
      statistic: 'Sum',
      period,
    });
    const agentErrorTotal = new cloudwatch.MathExpression({
      expression: 'chatSquare + chatSetmore + twilioSquare + twilioSetmore',
      usingMetrics: {
        chatSquare: agentErrorChatSquare,
        chatSetmore: agentErrorChatSetmore,
        twilioSquare: agentErrorTwilioSquare,
        twilioSetmore: agentErrorTwilioSetmore,
      },
      period,
      label: 'Agent errors (all)',
    });

    const agentLatencyChatSquare = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentResponseLatencyMs',
      dimensionsMap: { endpoint: 'chat', provider: 'square' },
      statistic: 'p95',
      period,
    });
    const agentLatencyChatSetmore = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentResponseLatencyMs',
      dimensionsMap: { endpoint: 'chat', provider: 'setmore' },
      statistic: 'p95',
      period,
    });
    const agentLatencyTwilioSquare = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentResponseLatencyMs',
      dimensionsMap: { endpoint: 'twilio_chat', provider: 'square' },
      statistic: 'p95',
      period,
    });
    const agentLatencyTwilioSetmore = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'AgentResponseLatencyMs',
      dimensionsMap: { endpoint: 'twilio_chat', provider: 'setmore' },
      statistic: 'p95',
      period,
    });
    const agentLatencyP95 = new cloudwatch.MathExpression({
      expression: 'MAX(MAX(chatSquare, chatSetmore), MAX(twilioSquare, twilioSetmore))',
      usingMetrics: {
        chatSquare: agentLatencyChatSquare,
        chatSetmore: agentLatencyChatSetmore,
        twilioSquare: agentLatencyTwilioSquare,
        twilioSetmore: agentLatencyTwilioSetmore,
      },
      period,
      label: 'Agent latency p95 (max)',
    });

    const maxTokensReached = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,MaxTokensReachedCount} MetricName=\"MaxTokensReachedCount\"', 'Sum', 300)",
      period,
      label: 'Max tokens reached',
    });

    const setmoreApiErrors = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,SetmoreApiErrorCount} MetricName=\"SetmoreApiErrorCount\"', 'Sum', 300)",
      period,
      label: 'Setmore API errors',
    });

    const setmoreApiLatencyP95 = new cloudwatch.MathExpression({
      expression: "MAX(SEARCH('{VakDeepGram,SetmoreApiLatencyMs} MetricName=\"SetmoreApiLatencyMs\"', 'p95', 300))",
      period,
      label: 'Setmore API latency p95',
    });

    const squareApiErrors = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,SquareApiErrorCount} MetricName=\"SquareApiErrorCount\"', 'Sum', 300)",
      period,
      label: 'Square API errors',
    });

    const squareApiLatencyP95 = new cloudwatch.MathExpression({
      expression: "MAX(SEARCH('{VakDeepGram,SquareApiLatencyMs} MetricName=\"SquareApiLatencyMs\"', 'p95', 300))",
      period,
      label: 'Square API latency p95',
    });

    const deepgramSessionErrors = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,DeepgramSessionErrorCount} MetricName=\"DeepgramSessionErrorCount\"', 'Sum', 300)",
      period,
      label: 'Deepgram session errors',
    });

    const deepgramSessionStarts = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,DeepgramSessionStartCount} MetricName=\"DeepgramSessionStartCount\"', 'Sum', 300)",
      period,
      label: 'Deepgram session starts',
    });

    const contextResolveErrors = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,BusinessContextResolveErrorCount} MetricName=\"BusinessContextResolveErrorCount\"', 'Sum', 300)",
      period,
      label: 'Business context resolve errors',
    });

    const contextResolveLatencyP95 = new cloudwatch.MathExpression({
      expression: "MAX(SEARCH('{VakDeepGram,BusinessContextResolveLatencyMs} MetricName=\"BusinessContextResolveLatencyMs\"', 'p95', 300))",
      period,
      label: 'Business context resolve latency p95',
    });

    const missingBusinessNumber = new cloudwatch.MathExpression({
      expression: "SEARCH('{VakDeepGram,MissingBusinessNumberCount} MetricName=\"MissingBusinessNumberCount\"', 'Sum', 300)",
      period,
      label: 'Missing business number',
    });

    const smsErrors = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'SmsSendErrorCount',
      dimensionsMap: { channel: 'sms' },
      statistic: 'Sum',
      period,
    });

    const whatsappErrors = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'WhatsappSendErrorCount',
      dimensionsMap: { channel: 'whatsapp' },
      statistic: 'Sum',
      period,
    });

    const smsSends = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'SmsSendCount',
      dimensionsMap: { channel: 'sms' },
      statistic: 'Sum',
      period,
    });

    const whatsappSends = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'WhatsappSendCount',
      dimensionsMap: { channel: 'whatsapp' },
      statistic: 'Sum',
      period,
    });

    const activeConnectionsWs = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'ActiveConnections',
      dimensionsMap: { endpoint: 'ws' },
      statistic: 'Average',
      period,
    });

    const activeConnectionsTwilio = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'ActiveConnections',
      dimensionsMap: { endpoint: 'twilio_ws' },
      statistic: 'Average',
      period,
    });

    const forwardedCallErrors = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'ForwardedCallErrorCount',
      dimensionsMap: { endpoint: 'twilio' },
      statistic: 'Sum',
      period,
    });

    const callDurationWsP95 = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'CallDurationMs',
      dimensionsMap: { endpoint: 'ws' },
      statistic: 'p95',
      period,
    });

    const callDurationTwilioP95 = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'CallDurationMs',
      dimensionsMap: { endpoint: 'twilio_ws' },
      statistic: 'p95',
      period,
    });

    const userMessagesPerSessionChat = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'UserMessagesPerSession',
      dimensionsMap: { endpoint: 'chat' },
      statistic: 'Average',
      period,
    });

    const userMessagesPerSessionTwilio = new cloudwatch.Metric({
      namespace: 'VakDeepGram',
      metricName: 'UserMessagesPerSession',
      dimensionsMap: { endpoint: 'twilio_chat' },
      statistic: 'Average',
      period,
    });

    const alarmTopic = new sns.Topic(this, 'VakMonitoringAlarms', {
      topicName: 'vak-monitoring-alarms',
      displayName: 'Vak Monitoring Alarms',
    });

    alarmTopic.addSubscription(
      new subscriptions.EmailSubscription('nag@tutzi.ai')
    );

    const alarmAction = new cloudwatchActions.SnsAction(alarmTopic);

    const cpuAlarm = new cloudwatch.Alarm(this, 'VakDeepGramCpuHigh', {
      metric: cpuUtilization,
      threshold: 75,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'VakDeepGram ECS CPU utilization is high.',
    });
    cpuAlarm.addAlarmAction(alarmAction);

    const memoryAlarm = new cloudwatch.Alarm(this, 'VakDeepGramMemoryHigh', {
      metric: memoryUtilization,
      threshold: 80,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'VakDeepGram ECS memory utilization is high.',
    });
    memoryAlarm.addAlarmAction(alarmAction);

    const tasksAlarm = new cloudwatch.Alarm(this, 'VakDeepGramTasksBelowDesired', {
      metric: runningLessThanDesired,
      threshold: 0.5,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.BREACHING,
      alarmDescription: 'VakDeepGram running tasks are below desired count.',
    });
    tasksAlarm.addAlarmAction(alarmAction);

    const alb5xxAlarm = new cloudwatch.Alarm(this, 'VakAlb5xx', {
      metric: albHttp5xx,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'ALB is returning target 5xx errors.',
    });
    alb5xxAlarm.addAlarmAction(alarmAction);

    const albLatencyAlarm = new cloudwatch.Alarm(this, 'VakAlbLatencyP90', {
      metric: albTargetResponseTimeP90,
      threshold: 1,
      evaluationPeriods: 3,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'ALB p90 target response time is elevated.',
    });
    albLatencyAlarm.addAlarmAction(alarmAction);

    const unhealthyAlarm = new cloudwatch.Alarm(this, 'VakTargetUnhealthyHosts', {
      metric: unhealthyHosts,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Target group has unhealthy hosts.',
    });
    unhealthyAlarm.addAlarmAction(alarmAction);

    const logErrorAlarm = new cloudwatch.Alarm(this, 'VakDeepGramErrorsInLogs', {
      metric: errorMetric,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Errors detected in VakDeepGram logs.',
    });
    logErrorAlarm.addAlarmAction(alarmAction);

    const agentErrorAlarm = new cloudwatch.Alarm(this, 'VakAgentErrors', {
      metric: agentErrorTotal,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Agent invocation errors detected.',
    });
    agentErrorAlarm.addAlarmAction(alarmAction);

    const agentLatencyAlarm = new cloudwatch.Alarm(this, 'VakAgentLatencyHigh', {
      metric: agentLatencyP95,
      threshold: 3000,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Agent response latency p95 is high.',
    });
    agentLatencyAlarm.addAlarmAction(alarmAction);

    const smsErrorAlarm = new cloudwatch.Alarm(this, 'VakSmsSendErrors', {
      metric: smsErrors,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'SMS delivery errors detected.',
    });
    smsErrorAlarm.addAlarmAction(alarmAction);

    const whatsappErrorAlarm = new cloudwatch.Alarm(this, 'VakWhatsappSendErrors', {
      metric: whatsappErrors,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'WhatsApp delivery errors detected.',
    });
    whatsappErrorAlarm.addAlarmAction(alarmAction);

    const forwardedErrorAlarm = new cloudwatch.Alarm(this, 'VakForwardedCallErrors', {
      metric: forwardedCallErrors,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Forwarded call errors detected.',
    });
    forwardedErrorAlarm.addAlarmAction(alarmAction);

    const callDurationAlarm = new cloudwatch.Alarm(this, 'VakCallDurationHigh', {
      metric: callDurationTwilioP95,
      threshold: 5400000,
      evaluationPeriods: 2,
      datapointsToAlarm: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Twilio call duration p95 is unusually high (possible stuck sessions).',
    });
    callDurationAlarm.addAlarmAction(alarmAction);

    const ddbThrottleAlarm = new cloudwatch.Alarm(this, 'VakSessionsDdbThrottles', {
      metric: ddbThrottles,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'DynamoDB throttling detected for Sessions table.',
    });
    ddbThrottleAlarm.addAlarmAction(alarmAction);

    const serviceDashboard = new cloudwatch.Dashboard(this, 'VakDeepGramDashboard', {
      dashboardName: 'VakDeepGram-Service',
    });

    serviceDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: '# VakDeepGram Service Overview',
        height: 1,
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ECS CPU / Memory',
        left: [cpuUtilization, memoryUtilization],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Running vs Desired Tasks',
        left: [runningTasks, desiredTasks],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Requests',
        left: [albRequestCount],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Target Response Time (p90)',
        left: [albTargetResponseTimeP90],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB 4xx / 5xx',
        left: [albHttp4xx, albHttp5xx],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Target Group Health',
        left: [healthyHosts, unhealthyHosts],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Log Errors',
        left: [errorMetric],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Tool Errors (All)',
        left: [toolErrorSearch],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Agent Errors / Max Tokens',
        left: [agentErrorTotal, maxTokensReached],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Agent Latency p95 (Max)',
        left: [agentLatencyP95],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'API Errors (Setmore vs Square)',
        left: [setmoreApiErrors, squareApiErrors],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'API Latency p95 (Setmore vs Square)',
        left: [setmoreApiLatencyP95, squareApiLatencyP95],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Deepgram Sessions (Starts / Errors)',
        left: [deepgramSessionStarts, deepgramSessionErrors],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Business Context Resolve (Errors / p95)',
        left: [contextResolveErrors, contextResolveLatencyP95],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Missing Business Number',
        left: [missingBusinessNumber],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Tool Latency p95 (Max)',
        left: [toolLatencyP95],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Forwarded Call Errors',
        left: [forwardedCallErrors],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Active Connections (WS / Twilio)',
        left: [activeConnectionsWs, activeConnectionsTwilio],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Call Duration p95 (WS vs Twilio)',
        left: [callDurationWsP95, callDurationTwilioP95],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'User Messages per Session (Avg)',
        left: [userMessagesPerSessionChat, userMessagesPerSessionTwilio],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Outbound Messages (SMS / WhatsApp)',
        left: [smsSends, whatsappSends],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Outbound Message Errors (SMS / WhatsApp)',
        left: [smsErrors, whatsappErrors],
        width: 24,
      }),
    );

    const infraDashboard = new cloudwatch.Dashboard(this, 'VakInfraDashboard', {
      dashboardName: 'VakInfra-Core',
    });

    const albConnections = alb.metrics.activeConnectionCount({ period });
    const albNewConnections = alb.metrics.newConnectionCount({ period });
    const albProcessedBytes = alb.metrics.processedBytes({ period, statistic: 'Sum' });
    const requestsPerTarget = new cloudwatch.Metric({
      namespace: 'AWS/ApplicationELB',
      metricName: 'RequestCountPerTarget',
      dimensionsMap: {
        TargetGroup: targetGroup.targetGroupFullName,
        LoadBalancer: alb.loadBalancerFullName,
      },
      statistic: 'Sum',
      period,
    });

    infraDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: '# Vak Infrastructure Metrics',
        height: 1,
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Sessions DynamoDB: Consumed Read/Write',
        left: [ddbConsumedRead, ddbConsumedWrite],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Sessions DynamoDB: Throttles',
        left: [ddbThrottles],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Artifacts Bucket Size (Bytes)',
        left: [s3BucketSize],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Artifacts Bucket Objects',
        left: [s3Requests],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Requests / Latency',
        left: [albRequestCount],
        right: [albTargetResponseTimeP90],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Connections',
        left: [albConnections, albNewConnections],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Processed Bytes',
        left: [albProcessedBytes],
        width: 24,
      }),
      new cloudwatch.GraphWidget({
        title: 'Requests per Target',
        left: [requestsPerTarget],
        width: 24,
      }),
    );

    new cdk.CfnOutput(this, 'VakAlarmTopicArn', {
      value: alarmTopic.topicArn,
      description: 'SNS topic ARN for Vak monitoring alarms.',
    });
  }
}

function elbCode(code: '4xx' | '5xx') {
  return code === '4xx'
    ? elbv2.HttpCodeTarget.TARGET_4XX_COUNT
    : elbv2.HttpCodeTarget.TARGET_5XX_COUNT;
}
