# Frontend image: build the Vite app, then serve the static bundle with nginx.
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
# The browser (on the host) reaches the API via the published port on localhost.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
# Typecheck before bundling: `vite build` (esbuild) strips types without checking,
# so tsc --noEmit is what actually fails the build on a type error.
RUN npm run typecheck
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
