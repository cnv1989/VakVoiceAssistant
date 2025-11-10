import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, PutCommand } from '@aws-sdk/lib-dynamodb';
import { validateApiGatewayRequest } from '../middleware/auth';

const ddbClient = new DynamoDBClient({ region: process.env.REGION || 'us-west-2' });
const docClient = DynamoDBDocumentClient.from(ddbClient);
const tableName = process.env.DDB_TABLE || 'Sessions';

export async function connectRoute(fastify: FastifyInstance) {
  fastify.post('/connect', async (request: FastifyRequest, reply: FastifyReply) => {
    // Validate request comes from API Gateway with IAM authorization
    const isValid = await validateApiGatewayRequest(request, reply);
    if (!isValid) {
      return reply.code(403).send({ 
        error: 'Forbidden',
        message: 'Request must come from API Gateway with valid IAM authorization'
      });
    }

    const connectionId = (request.headers['x-amzn-connection-id'] || 
                          (request.body as any)?.connectionId) as string;
    
    if (!connectionId) {
      return reply.code(400).send({ error: 'Missing connection ID' });
    }

    // Store session in DynamoDB
    const ttl = Math.floor(Date.now() / 1000) + 3600; // 1 hour TTL
    
    try {
      await docClient.send(new PutCommand({
        TableName: tableName,
        Item: {
          sid: connectionId,
          ttl,
          createdAt: new Date().toISOString(),
        },
      }));

      fastify.log.info(`Connection established: ${connectionId}`);
      return { status: 'connected', connectionId };
    } catch (error) {
      fastify.log.error(`Error storing session: ${error}`);
      return reply.code(500).send({ error: 'Failed to store session' });
    }
  });
}
