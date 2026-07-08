# {{ project_name }} frontend — Next.js. Image bakes source + deps so it serves
# the app (default command) and the `node` profile (tsc/eslint/next build,
# command overridden at call time).
FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
