import Fastify from 'fastify';
import { PrismaClient } from '@prisma/client';

const fastify = Fastify({ logger: true });
const prisma = new PrismaClient();

fastify.register(async (instance) => {
  instance.get('/tasks', async (request, reply) => {
    return await prisma.task.findMany();
  });

  instance.post('/tasks', async (request, reply) => {
    const { title } = request.body as { title: string };
    if (!title || title.length > 100) {
      return reply.code(400).send({ error: 'Invalid title' });
    }
    const task = await prisma.task.create({ data: { title } });
    return reply.code(201).send(task);
  });

  instance.put('/tasks/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    const { status } = request.body as { status: 'PENDING' | 'COMPLETED' };
    try {
      const task = await prisma.task.update({ where: { id }, data: { status } });
      return task;
    } catch {
      return reply.code(404).send({ error: 'Task not found' });
    }
  });

  instance.delete('/tasks/:id', async (request, reply) => {
    const { id } = request.params as { id: string };
    try {
      await prisma.task.delete({ where: { id } });
      return reply.code(204).send();
    } catch {
      return reply.code(404).send({ error: 'Task not found' });
    }
  });
});

fastify.listen({ port: 3000, host: '0.0.0.0' }, (err) => {
  if (err) {
    fastify.log.error(err);
    process.exit(1);
  }
});
