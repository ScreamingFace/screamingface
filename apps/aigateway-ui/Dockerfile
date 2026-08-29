# Build context is the REPO ROOT, matching apps/aigateway/Dockerfile:
#   docker build -f apps/aigateway-ui/Dockerfile .
#
# The node version is pinned by .nvmrc (22) rather than repeated here as a literal — see the ARG
# below. Debian slim rather than Alpine to match the aigateway image's base family: Next.js pulls
# optional native/wasm binaries (the @emnapi/* entries in the lockfile), and musl resolves a
# different set of those than glibc does, so an Alpine build can succeed while installing
# artifacts that were never what CI tested.

ARG NODE_VERSION=22


FROM node:${NODE_VERSION}-bookworm-slim AS deps

WORKDIR /app

# Only the manifests, so this layer caches on dependency changes rather than on every source edit.
COPY apps/aigateway-ui/package.json apps/aigateway-ui/package-lock.json ./

# `npm ci` — never `npm install`. It installs FROM the lockfile and fails outright when the two
# disagree, so a drifted lock breaks the build here instead of producing an image whose dependency
# tree nothing ever tested. Dev dependencies are needed: `next build` runs TypeScript.
RUN --mount=type=cache,target=/root/.npm \
    npm ci


FROM node:${NODE_VERSION}-bookworm-slim AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY apps/aigateway-ui/ ./

# Telemetry is a network call from a build of an internal admin console. Off.
ENV NEXT_TELEMETRY_DISABLED=1

# Produces .next/standalone — a self-contained server carrying only the modules actually reached,
# which is why the runtime stage below installs nothing at all.
RUN npm run build


FROM node:${NODE_VERSION}-bookworm-slim AS runtime

LABEL org.opencontainers.image.source="https://github.com/ScreamingFace/screamingface" \
      org.opencontainers.image.description="ScreamingFace AI Gateway admin console" \
      org.opencontainers.image.licenses="MIT"

# HOSTNAME must be 0.0.0.0: the standalone server binds 'localhost' by default, which in a
# container accepts nothing from outside it — the Pod would pass its own HEALTHCHECK (loopback)
# and fail every kubelet probe (Pod IP), which reads as a broken probe rather than a bind address.
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=9107 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# No `useradd` here, deliberately — the node images already ship a `node` user at UID 1000, so
# creating one fails the build with "UID 1000 is not unique". (aigateway's Dockerfile does create
# its user, because python:3.12-slim ships no UID 1000; the pattern does not transfer.) UID 1000
# is what the chart's securityContext pins via runAsUser.
#
# Three distinct pieces, and the two after the server are NOT optional:
#   standalone/  the traced server and its node_modules subset
#   static/      the hashed JS/CSS build output; without it every page loads unstyled and inert
#   public/      served assets — including theme-init.js, which applies the stored theme BEFORE
#                first paint (OME-709). Missing, the console renders light then visibly flips.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node

EXPOSE 9107

# Node's own fetch — no curl in the image, and nothing to install to get one.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:9107/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
