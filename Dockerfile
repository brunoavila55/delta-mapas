FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM rust:1.99.0-slim-bookworm AS build
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY --from=frontend /src/ui ./src/ui
COPY migrations ./migrations
RUN cargo build --release --locked

FROM debian:bookworm-slim AS runtime
WORKDIR /app
COPY --from=build /app/target/release/delta-analysis /usr/local/bin/delta-analysis
COPY examples ./examples
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
STOPSIGNAL SIGINT
ENTRYPOINT ["delta-analysis"]
CMD ["--help"]
