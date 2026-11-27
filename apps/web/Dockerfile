FROM node:20-alpine
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install
COPY apps/web ./
# Vite alias resolves to /packages/api-client when the config lives in /app.
COPY packages/api-client /packages/api-client
EXPOSE 5173
CMD ["npm", "run", "dev"]
