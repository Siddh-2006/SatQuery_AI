# ui/ -- the existing React/Vite frontend (see DESIGN.md). Two-stage
# build: compile the static bundle with Node, then serve it with a tiny
# static file server -- no Node runtime needed in the final image.
FROM node:20-slim AS build
WORKDIR /ui
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# VITE_API_BASE_URL is baked in at build time (Vite env vars are resolved
# at build, not at container start) -- override it with a build arg if the
# orchestrator lives somewhere other than the docker-compose default.
ARG VITE_API_BASE_URL=http://localhost:8080
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:20-slim AS run
WORKDIR /ui
RUN npm install -g serve@14
COPY --from=build /ui/dist ./dist
EXPOSE 80
CMD ["serve", "-s", "dist", "-l", "80"]
