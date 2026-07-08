import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import { Construct } from 'constructs';

export interface VakNetworkStackProps extends cdk.StackProps {
  /** ECR repository name for the VakDeepGram image. Defaults to 'vak-deepgram'. */
  ecrRepositoryName?: string;
  /** Number of NAT gateways (one per AZ costs more; 1 is fine for most deployments). */
  natGateways?: number;
}

export class VakNetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly deepgramEcrRepo: ecr.Repository;

  constructor(scope: Construct, id: string, props?: VakNetworkStackProps) {
    super(scope, id, props);

    // VPC with 2 AZs — one NAT gateway by default keeps costs low for a first deploy.
    this.vpc = new ec2.Vpc(this, 'VakVpc', {
      maxAzs: 2,
      natGateways: props?.natGateways ?? 1,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });

    // ECR repository for the VakDeepGram image. Created here (not imported) so a
    // brand-new AWS account can deploy end to end with a single `cdk deploy`.
    this.deepgramEcrRepo = new ecr.Repository(this, 'VakDeepGramRepo', {
      repositoryName: props?.ecrRepositoryName ?? 'vak-deepgram',
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        { description: 'Keep last 20 images', maxImageCount: 20 },
      ],
    });

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId, description: 'VPC ID' });
    new cdk.CfnOutput(this, 'DeepgramEcrRepoUri', {
      value: this.deepgramEcrRepo.repositoryUri,
      description: 'ECR repository URI — push images here (see scripts/deploy-to-ecr.sh)',
    });
  }
}
