
# Task MVP Foundation
# Architecture Decision Record (ADR-001)

## System Design
- Topology: Containerized micro-services using docker-compose.
- Network: API (port 3000), Frontend (port 5173), Postgres (port 5432).
- Service Boundaries: 
    - /apps/api: Fastify, Prisma ORM, TypeScript.
    - /apps/web: React, Vite, TanStack Query.
    - /packages/contracts: Shared TypeScript types.
- Data Flow: Client sends optimistic update via React -> UI updates instantly -> API call initiates -> Reconcile.

## API Contract
Base URL: /api/v1
- POST /tasks: {title: string}
- GET /tasks: returns Task[]
- PUT /tasks/:id: {status: 'PENDING' | 'COMPLETED'}
- DELETE /tasks/:id: returns 204
