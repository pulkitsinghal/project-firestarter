# Storyboard runner — Playwright with browsers preinstalled. Pinned to match the
# playwright npm version so no browser re-download is needed.
FROM mcr.microsoft.com/playwright:v1.49.1-jammy

WORKDIR /app
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

COPY package.json ./
RUN npm install

COPY storyboard.mjs ./
CMD ["node", "storyboard.mjs"]
