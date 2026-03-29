import fastify from 'fastify';
import { PrismaClient } from '@prisma/client';

const server = fastify();
const prisma = new PrismaClient();

// Task creation with SEC-01 validation (1-100 characters)
server.post('/api/v1/tasks', async (request, reply) => {
  const body = request.body as { title: string };
  if (!body || typeof body.title !== 'string' || body.title.length < 1 || body.title.length > 100) {
    return reply.status(400).send({ error: 'Title must be between 1 and 100 characters' });
  }
  
  try {
    const task = await prisma.task.create({ data: { title: body.title, status: 'PENDING' } });
    return reply.status(201).send(task);
  } catch (error) {
    return reply.status(500).send({ error: 'Internal Server Error' });
  }
});

server.get('/api/v1/tasks', async (request, reply) => {
  try {
    const tasks = await prisma.task.findMany();
    return tasks;
  } catch (error) {
    return reply.status(500).send({ error: 'Internal Server Error' });
  }
});

server.put('/api/v1/tasks/:id', async (request, reply) => {
  const { id } = request.params as { id: string };
  const body = request.body as { status: 'PENDING' | 'COMPLETED' };
  
  if (!['PENDING', 'COMPLETED'].includes(body.status)) {
    return reply.status(400).send({ error: 'Invalid status' });
  }

  try {
    const task = await prisma.task.update({ where: { id }, data: { status: body.status } });
    return task;
  } catch (e) {
    return reply.status(404).send({ error: 'Task not found' });
  }
});

server.delete('/api/v1/tasks/:id', async (request, reply) => {
  const { id } = request.params as { id: string };
  try {
    await prisma.task.delete({ where: { id } });
    return reply.status(204).send();
  } catch (e) {
    return reply.status(404).send({ error: 'Task not found' });
  }
});

const start = async () => {
  try {
    await server.listen({ port: 3000, host: '0.0.0.0' });
    console.log('Server listening on port 3000');
  } catch (err) {
    server.log.error(err);
    process.exit(1);
  }
};

start();
