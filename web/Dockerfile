# UGC Studio web app: multi-stage build -> small standalone Node runtime on port 3000.
#   docker build -t ugc-studio-web web/
#   docker run -p 3000:3000 -e UGC_API_URL=http://host.docker.internal:8000 ugc-studio-web

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Rewrites are resolved at build time: build with a placeholder, docker-entrypoint.sh swaps in UGC_API_URL at start.
ENV UGC_API_URL=http://ugc-api-url-placeholder:8000
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    UGC_API_URL=http://api:8000
RUN addgroup -S app && adduser -S app -G app && chown app:app /app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
COPY --chown=app:app docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN for f in server.js .next/routes-manifest.json .next/required-server-files.json; do cp "$f" "$f.orig"; done
USER app
EXPOSE 3000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node", "server.js"]
