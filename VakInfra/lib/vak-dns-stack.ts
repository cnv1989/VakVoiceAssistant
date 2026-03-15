import * as cdk from 'aws-cdk-lib';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import { Construct } from 'constructs';

/**
 * Shared DNS stack for groommate.ai.
 * Creates the Route53 hosted zone and a wildcard ACM certificate
 * used by all stage-specific ALBs.
 *
 * After deploying this stack, update GoDaddy nameservers with the
 * NS records output from GroomMateNameServers.
 */
export class VakDnsStack extends cdk.Stack {
  public readonly hostedZone: route53.HostedZone;
  public readonly wildcardCertificate: acm.Certificate;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    // Public hosted zone for groommate.ai
    this.hostedZone = new route53.HostedZone(this, 'GroomMateZone', {
      zoneName: 'groommate.ai',
      comment: 'GroomMate production DNS zone',
    });

    // Wildcard + apex certificate for *.groommate.ai and groommate.ai
    // DNS-validated via the hosted zone above (auto-creates validation records).
    // Used by all stage ALBs (alpha-api, beta-api, api).
    this.wildcardCertificate = new acm.Certificate(this, 'WildcardCert', {
      domainName: '*.groommate.ai',
      subjectAlternativeNames: ['groommate.ai'],
      validation: acm.CertificateValidation.fromDns(this.hostedZone),
    });

    // ─── Outputs ──────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'HostedZoneId', {
      value: this.hostedZone.hostedZoneId,
      description: 'Route53 Hosted Zone ID for groommate.ai',
      exportName: 'GroomMateHostedZoneId',
    });

    new cdk.CfnOutput(this, 'NameServers', {
      value: cdk.Fn.join(', ', this.hostedZone.hostedZoneNameServers!),
      description: 'Update these 4 NS records in GoDaddy for groommate.ai',
      exportName: 'GroomMateNameServers',
    });

    new cdk.CfnOutput(this, 'CertArn', {
      value: this.wildcardCertificate.certificateArn,
      description: 'Wildcard ACM certificate ARN for *.groommate.ai (us-west-2)',
      exportName: 'GroomMateCertArn',
    });
  }
}
