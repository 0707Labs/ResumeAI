# The Next.js server (docs/deploy.md, "Railway"). Build from frontend/:
#   docker build --build-arg BACKEND_URL=http://api.railway.internal:8000 -t resume-tailor-web frontend
# BACKEND_URL is needed at build time (rewrites are fixed then) and again at runtime
# (server-side reads). NEXT_PUBLIC_* values are inlined into the browser bundle at build.

FROM node:24-bookworm-slim AS deps
WORKDIR /build
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund

FROM deps AS build
ARG BACKEND_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_SUPPORT_EMAIL
ARG NEXT_PUBLIC_GRIEVANCE_OFFICER_NAME
ARG NEXT_PUBLIC_GRIEVANCE_OFFICER_EMAIL
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

FROM node:24-bookworm-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /srv/frontend
# The standalone server and its traced dependencies, plus the assets it serves as files.
COPY --from=build /build/.next/standalone ./
COPY --from=build /build/.next/static ./.next/static
COPY --from=build /build/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
