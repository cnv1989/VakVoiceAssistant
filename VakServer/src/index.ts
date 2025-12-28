import Fastify from 'fastify';
import { healthRoute } from './routes/health';
import { connectRoute } from './routes/connect';
import { disconnectRoute } from './routes/disconnect';
import { defaultRoute } from './routes/default';
import { registerWebSocketHandler } from './websocket-handler';

const fastify = Fastify({
  logger: true,
});

const PORT = parseInt(process.env.PORT || '8080', 10);
const HOST = process.env.HOST || '0.0.0.0';
const LOCAL_MODE = process.env.LOCAL_MODE === 'true' || !process.env.ALB_DNS;

// Register routes
fastify.register(healthRoute);
// Note: connect/disconnect/default routes are for API Gateway integration
// When using direct ALB WebSocket, these routes are not needed
// But keeping them for backward compatibility
fastify.register(connectRoute);
fastify.register(disconnectRoute);
fastify.register(defaultRoute);

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
