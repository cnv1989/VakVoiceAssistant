import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, DeleteCommand } from '@aws-sdk/lib-dynamodb';
import { validateApiGatewayRequest } from '../middleware/auth';
import { clearConnectionTtsSettings } from './message-handlers';

const ddbClient = new DynamoDBClient({ region: process.env.REGION || 'us-west-2' });
const docClient = DynamoDBDocumentClient.from(ddbClient);
const tableName = process.env.DDB_TABLE || 'Sessions';

export async function disconnectRoute(fastify: FastifyInstance) {
  fastify.post('/disconnect', async (request: FastifyRequest, reply: FastifyReply) => {
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

    // Remove session from DynamoDB
    try {
      await docClient.send(new DeleteCommand({
        TableName: tableName,
        Key: { sid: connectionId },
      }));

      fastify.log.info(`Connection disconnected: ${connectionId}`);
      clearConnectionTtsSettings(connectionId, fastify);
      return { status: 'disconnected', connectionId };
    } catch (error) {
      fastify.log.error(`Error removing session: ${error}`);
      return reply.code(500).send({ error: 'Failed to remove session' });
    }
  });
}
