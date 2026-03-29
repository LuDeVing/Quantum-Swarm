FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

# Assume source is in /apps/api if per ADR, but aligning with current workspace
# For now, just ensuring it starts correctly.
CMD ["npm", "run", "start"]
