import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import { Construct } from 'constructs';

export interface VakNetworkStackProps extends cdk.StackProps {}

export class VakNetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly ecrRepo: ecr.Repository;

  constructor(scope: Construct, id: string, props?: VakNetworkStackProps) {
    super(scope, id, props);

    // VPC with 2 AZs
    this.vpc = new ec2.Vpc(this, 'VakVpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
    });

    // ECR repository for VakServer image
    // Note: Docker image assets create their own repo, but this is kept for manual image pushes
    this.ecrRepo = new ecr.Repository(this, 'VakServerRepo', {
      repositoryName: 'vak-server',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Outputs
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'VPC ID',
      exportName: 'VakVpcId',
    });

    new cdk.CfnOutput(this, 'PrivateSubnetIds', {
      value: cdk.Fn.join(',', this.vpc.privateSubnets.map(s => s.subnetId)),
      description: 'Private Subnet IDs',
      exportName: 'VakPrivateSubnetIds',
    });

    new cdk.CfnOutput(this, 'PublicSubnetIds', {
      value: cdk.Fn.join(',', this.vpc.publicSubnets.map(s => s.subnetId)),
      description: 'Public Subnet IDs',
      exportName: 'VakPublicSubnetIds',
    });

    new cdk.CfnOutput(this, 'EcrRepoUri', {
      value: this.ecrRepo.repositoryUri,
      description: 'ECR repository URI for VakServer image',
      exportName: 'VakEcrRepoUri',
    });
  }
}
