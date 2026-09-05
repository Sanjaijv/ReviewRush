FROM node:20-slim AS deps
WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
# rewrites() in next.config.ts is evaluated once, at `next build` time, and
# baked into .next/required-server-files.json - not re-read at `next start`,
# so this must be a build arg rather than a plain runtime environment
# variable on the run stage below.
ARG BACKEND_ORIGIN=http://localhost:8010
ENV BACKEND_ORIGIN=${BACKEND_ORIGIN}
RUN npm run build

FROM node:20-slim AS run
WORKDIR /srv
ENV NODE_ENV=production
COPY --from=build /srv/public ./public
COPY --from=build /srv/.next ./.next
COPY --from=build /srv/node_modules ./node_modules
COPY --from=build /srv/package.json ./package.json
COPY --from=build /srv/next.config.ts ./next.config.ts
EXPOSE 3000
CMD ["npm", "start"]
