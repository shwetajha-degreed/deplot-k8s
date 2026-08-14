# syntax=docker/dockerfile:1.7
# Build context: repo root (docker build -f frontend/Dockerfile .)

FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci


FROM node:22-alpine AS builder
WORKDIR /app

# Baked into the client bundle at build time; must be a real URL, not a placeholder.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build


FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -S -g 1001 app \
 && adduser  -S -u 1001 -G app app

COPY --from=builder /app/package.json      ./package.json
COPY --from=builder /app/package-lock.json ./package-lock.json
COPY --from=builder /app/node_modules      ./node_modules
COPY --from=builder /app/.next             ./.next
COPY --from=builder /app/public            ./public
COPY --from=builder /app/next.config.js    ./next.config.js

RUN chown -R app:app /app
USER app

EXPOSE 3000
CMD ["npm", "start"]
