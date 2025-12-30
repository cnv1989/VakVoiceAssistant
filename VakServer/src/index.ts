import Fastify from 'fastify';
import { healthRoute } from './routes/health';
import { registerWebSocketHandler } from './websocket-handler';

const fastify = Fastify({
  logger: true,
});

const PORT = parseInt(process.env.PORT || '8080', 10);
const HOST = process.env.HOST || '0.0.0.0';
const LOCAL_MODE = process.env.LOCAL_MODE === 'true' || !process.env.ALB_DNS;

// Register routes
fastify.register(healthRoute);

// Register WebSocket handler for direct connections (ALB or local)
// WebSocket connections go directly to /ws endpoint
fastify.register(registerWebSocketHandler);

const start = async () => {
  try {
    await fastify.listen({ port: PORT, host: HOST });
    fastify.log.info(`Server listening on ${HOST}:${PORT}`);
    if (LOCAL_MODE) {
      fastify.log.info(`Local mode enabled - WebSocket server available at ws://localhost:${PORT}/ws`);
    }
  } catch (err) {
    fastify.log.error(err);
    process.exit(1);
  }
};

start();
