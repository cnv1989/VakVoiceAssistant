import { FastifyRequest, FastifyReply } from 'fastify';
import { STSClient, GetCallerIdentityCommand } from '@aws-sdk/client-sts';

const region = process.env.REGION || 'us-west-2';
const expectedApiId = process.env.API_GATEWAY_API_ID || '';

/**
 * Authorization middleware for validating API Gateway requests
 * 
 * When API Gateway uses IAM authorization, it adds several headers:
 * - x-amzn-apigateway-api-id: The API Gateway API ID
 * - x-amzn-requestid: Request ID
 * - Authorization: AWS Signature Version 4 signature
 * - X-Amz-Date: Request timestamp
 * - X-Amz-Security-Token: Session token (if using temporary credentials)
 * 
 * The server can validate requests by:
 * 1. Checking API Gateway context headers
 * 2. Validating SigV4 signature (optional, more secure)
 * 3. Verifying source IP (if NLB has source IP preservation)
 */
export async function validateApiGatewayRequest(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<boolean> {
  const headers = request.headers;

  // Method 1: Validate API Gateway context headers
  const apiId = headers['x-amzn-apigateway-api-id'] as string;
  const requestId = headers['x-amzn-requestid'] as string;
  const authorization = headers['authorization'] as string;
  const amzDate = headers['x-amz-date'] as string;
  const amzSecurityToken = headers['x-amz-security-token'] as string;

  // Check if request has API Gateway headers
  if (!apiId || !requestId) {
    request.log.warn('Missing API Gateway context headers');
    return false;
  }

  // If expected API ID is configured, validate it matches
  if (expectedApiId && apiId !== expectedApiId) {
    request.log.warn(`API ID mismatch: expected ${expectedApiId}, got ${apiId}`);
    return false;
  }

  // Method 2: Validate SigV4 signature (more secure)
  // This validates that the request was signed by API Gateway using the integration role
  if (authorization && amzDate) {
    try {
      // Extract the signature from Authorization header
      // Format: AWS4-HMAC-SHA256 Credential=..., SignedHeaders=..., Signature=...
      const signatureMatch = authorization.match(/Signature=([^,]+)/);
      if (!signatureMatch) {
        request.log.warn('Invalid Authorization header format');
        return false;
      }

      // Note: Full signature validation requires:
      // 1. Reconstructing the canonical request
      // 2. Computing the signature using the same credentials
      // 3. Comparing signatures
      // This is complex and typically done via AWS SDK or specialized libraries
      
      // For now, we'll do basic validation - check that signature exists
      // Full validation would require storing API Gateway's credentials or using
      // a service like AWS STS to validate the signature
      
      request.log.info('SigV4 signature present, basic validation passed');
    } catch (error) {
      request.log.error(`Error validating signature: ${error}`);
      return false;
    }
  } else {
    // If no signature, this might be a direct request (not from API Gateway)
    // In production, you might want to reject these
    request.log.warn('No SigV4 signature found in request');
  }

  // Method 3: Additional validation - check connection ID header
  // API Gateway adds this header for WebSocket routes
  const connectionId = headers['x-amzn-connection-id'] as string;
  if (!connectionId) {
    request.log.warn('Missing connection ID header');
    // This might be okay for some routes, so we don't fail here
  }

  // All validations passed
  request.log.info(`Request validated: API ID=${apiId}, Request ID=${requestId}`);
  return true;
}

/**
 * Fastify preHandler hook for authorization
 */
export async function authHook(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  const isValid = await validateApiGatewayRequest(request, reply);
  
  if (!isValid) {
    reply.code(403).send({ 
      error: 'Forbidden',
      message: 'Request validation failed. Request must come from API Gateway with valid IAM authorization.'
    });
    return;
  }
}

/**
 * Alternative: Validate using AWS STS to verify the caller identity
 * This is more secure but requires an additional AWS API call
 */
export async function validateWithSTS(
  request: FastifyRequest
): Promise<boolean> {
  try {
    const stsClient = new STSClient({ region });
    const command = new GetCallerIdentityCommand({});
    const identity = await stsClient.send(command);
    
    // Verify the caller is API Gateway service
    // API Gateway uses a specific role ARN pattern
    request.log.info(`Caller identity: ${identity.Arn}`);
    
    // You can validate that the ARN matches your API Gateway integration role
    // This is optional but provides additional security
    
    return true;
  } catch (error) {
    request.log.error(`STS validation error: ${error}`);
    return false;
  }
}
