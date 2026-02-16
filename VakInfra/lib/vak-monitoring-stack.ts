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
