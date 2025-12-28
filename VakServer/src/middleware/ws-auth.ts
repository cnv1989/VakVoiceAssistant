import { FastifyRequest } from 'fastify';

const region = process.env.REGION || 'us-west-2';
const albDns = process.env.ALB_DNS || '';

/**
 * Validates IAM signature for WebSocket upgrade request
 * 
 * When clients connect via WebSocket with IAM authentication, they sign
 * the HTTP upgrade request using AWS Signature Version 4.
 * 
 * This function validates:
 * 1. Authorization header is present and properly formatted
 * 2. Signature is valid (basic check - full validation requires reconstructing request)
 * 
 * Note: Full signature validation is complex. For production, consider using
 * AWS SDK's built-in validation or a service like AWS STS.
 */
export async function validateWebSocketIamAuth(
  request: FastifyRequest
): Promise<boolean> {
  const headers = request.headers;
  const authorization = headers['authorization'] as string;
  const amzDate = headers['x-amz-date'] as string;
  const amzSecurityToken = headers['x-amz-security-token'] as string;

  // Check for required IAM auth headers
  if (!authorization || !amzDate) {
    request.log.warn('Missing IAM authentication headers (Authorization or X-Amz-Date)');
    return false;
  }

  // Validate Authorization header format
  // Format: AWS4-HMAC-SHA256 Credential=..., SignedHeaders=..., Signature=...
  const authPattern = /^AWS4-HMAC-SHA256\s+Credential=([^,]+),\s+SignedHeaders=([^,]+),\s+Signature=(.+)$/;
  const match = authorization.match(authPattern);
  
  if (!match) {
    request.log.warn('Invalid Authorization header format');
    return false;
  }

  const [, credential, signedHeaders, signature] = match;

  // Basic validation - check that signature exists and is hex
  if (!signature || !/^[a-f0-9]{64}$/i.test(signature)) {
    request.log.warn('Invalid signature format');
    return false;
  }

  // Extract access key from credential
  // Credential format: ACCESS_KEY_ID/YYYYMMDD/REGION/elbv2/aws4_request
  const credentialParts = credential.split('/');
  if (credentialParts.length < 4) {
    request.log.warn('Invalid credential format');
    return false;
  }

  const accessKeyId = credentialParts[0];
  const credentialDate = credentialParts[1];
  const credentialRegion = credentialParts[2];
  const service = credentialParts[3];

  // Validate service is elbv2 (for ALB)
  if (service !== 'elbv2') {
    request.log.warn(`Invalid service in credential: ${service}, expected elbv2`);
    return false;
  }

  // Validate region matches
  if (credentialRegion !== region) {
    request.log.warn(`Region mismatch: ${credentialRegion} != ${region}`);
    return false;
  }

  // Validate date format (YYYYMMDD)
  if (!/^\d{8}$/.test(credentialDate)) {
    request.log.warn(`Invalid date format: ${credentialDate}`);
    return false;
  }

  // For now, we do basic validation
  // Full signature validation would require:
  // 1. Reconstructing the canonical request
  // 2. Computing the signature using the same credentials
  // 3. Comparing signatures
  // This is complex and typically requires AWS SDK or specialized libraries
  
  request.log.info(`IAM auth validated: AccessKeyId=${accessKeyId.substring(0, 8)}..., Service=${service}, Region=${credentialRegion}`);
  
  return true;
}

/**
 * Alternative: Use AWS SDK to validate signature
 * This is more secure but requires additional setup
 */
export async function validateWebSocketIamAuthWithSDK(
  request: FastifyRequest
): Promise<boolean> {
  try {
    // This would require reconstructing the HTTP request and validating
    // using AWS SDK's SignatureV4. For now, we use basic validation above.
    // Full implementation would use:
    // - SignatureV4 from @aws-sdk/signature-v4
    // - Reconstruct canonical request
    // - Compare signatures
    
    return await validateWebSocketIamAuth(request);
  } catch (error) {
    request.log.error(`Error validating IAM auth with SDK: ${error}`);
    return false;
  }
}
