# syntax=docker/dockerfile:1
# {{ project_name }} frontend — Next.js. Image bakes source + deps so it serves
# the app (default command) and the `node` profile (tsc/eslint/next build,
# command overridden at call time).
FROM node:22-alpine

WORKDIR /app

# Deps first for layer caching. The BuildKit cache mount persists npm's download
# cache across builds (outside the image), so a dependency change reinstalls
# without re-fetching every unchanged package. The committed lockfile keeps
# local, CI, and production dependency graphs identical.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
