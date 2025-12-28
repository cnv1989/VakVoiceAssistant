/**
 * WebSocket IAM Authentication Signer
 * 
 * Signs WebSocket upgrade requests with AWS Signature Version 4
 * for ALB IAM authentication.
 * 
 * Note: Browser WebSocket API doesn't support custom headers directly.
 * This implementation signs the request and uses a workaround to include
 * the signature in the connection.
 */

import { SignatureV4 } from '@aws-sdk/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-browser';
import { HttpRequest } from '@aws-sdk/protocol-http';

interface AwsCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
}

/**
 * Get AWS credentials from environment or AWS SDK
 */
async function getAwsCredentials(): Promise<AwsCredentials> {
  // Try to get from environment variables first
  const accessKeyId = import.meta.env.VITE_AWS_ACCESS_KEY_ID;
  const secretAccessKey = import.meta.env.VITE_AWS_SECRET_ACCESS_KEY;
  const sessionToken = import.meta.env.VITE_AWS_SESSION_TOKEN;

  if (accessKeyId && secretAccessKey) {
    return {
      accessKeyId,
      secretAccessKey,
      sessionToken,
    };
  }

  // If not in env, try to use AWS SDK (requires AWS SDK to be loaded)
  // For browser, you might need to use AWS Cognito or other auth methods
  throw new Error('AWS credentials not found. Please set VITE_AWS_ACCESS_KEY_ID and VITE_AWS_SECRET_ACCESS_KEY');
}

/**
 * Sign WebSocket upgrade request for ALB IAM authentication
 * 
 * @param wsUrl WebSocket URL (e.g., ws://alb-dns/ws)
 * @param region AWS region
 * @returns Signed request with URL and headers
 */
export async function signWebSocketRequest(
  wsUrl: string,
  region: string = 'us-west-2'
): Promise<{ url: string; headers: Record<string, string> }> {
  try {
    const credentials = await getAwsCredentials();
    const url = new URL(wsUrl);
    
    // Create HTTP request for WebSocket upgrade
    const request = new HttpRequest({
      method: 'GET',
      protocol: url.protocol,
      hostname: url.hostname,
      port: url.port ? parseInt(url.port) : (url.protocol === 'wss:' ? 443 : 80),
      path: url.pathname + url.search,
      headers: {
        'Host': url.hostname,
        'Upgrade': 'websocket',
        'Connection': 'Upgrade',
        'Sec-WebSocket-Key': generateWebSocketKey(),
        'Sec-WebSocket-Version': '13',
      },
    });

    // Sign the request
    const signer = new SignatureV4({
      credentials,
      service: 'elbv2',
      region,
      sha256: Sha256,
    });

    const signedRequest = await signer.sign(request);

    // Extract authorization header
    const authHeader = signedRequest.headers['authorization'];
    const dateHeader = signedRequest.headers['x-amz-date'];
    const tokenHeader = signedRequest.headers['x-amz-security-token'];

    if (!authHeader || !dateHeader) {
      throw new Error('Failed to sign WebSocket request');
    }

    // Note: Browser WebSocket API doesn't support custom headers
    // We need to use a library that supports custom headers or use a different approach
    // For now, return the URL and headers separately
    // The actual WebSocket connection will need to be made with a library that supports headers
    
    return {
      url: wsUrl,
      headers: {
        'Authorization': authHeader,
        'X-Amz-Date': dateHeader,
        ...(tokenHeader && { 'X-Amz-Security-Token': tokenHeader }),
      },
    };
  } catch (error) {
    console.error('Error signing WebSocket URL:', error);
    throw error;
  }
}

/**
 * Generate WebSocket key for upgrade request
 */
function generateWebSocketKey(): string {
  const randomBytes = new Uint8Array(16);
  crypto.getRandomValues(randomBytes);
  return btoa(String.fromCharCode(...randomBytes));
}

/**
 * Create WebSocket connection with IAM authentication
 * 
 * Note: Browser WebSocket API doesn't support custom headers.
 * This function creates a WebSocket using a workaround:
 * 1. Signs the request to get authorization headers
 * 2. Uses a custom WebSocket implementation that supports headers
 * 
 * For now, returns the signed headers that need to be used with
 * a WebSocket library that supports custom headers.
 */
export async function getSignedWebSocketHeaders(
  wsUrl: string,
  region: string = 'us-west-2'
): Promise<Record<string, string>> {
  const signed = await signWebSocketRequest(wsUrl, region);
  return signed.headers;
}
