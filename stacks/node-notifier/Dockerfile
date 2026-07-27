FROM node:24.18.0-bookworm-slim AS base

WORKDIR /app
COPY package.json package-lock.json ./

FROM base AS production-dependencies
RUN npm ci --omit=dev && npm cache clean --force

FROM base AS test
ENV NODE_ENV=test
RUN npm ci && npm cache clean --force
COPY . .
USER node
CMD ["npm", "run", "test:all"]

FROM node:24.18.0-bookworm-slim AS runtime

ENV NODE_ENV=production
WORKDIR /app

COPY --from=production-dependencies --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node package.json ./
COPY --chown=node:node public ./public
COPY --chown=node:node src ./src

USER node
EXPOSE 3000
CMD ["node", "src/start-api.js"]
