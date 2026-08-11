ARG POSTGRES_IMAGE=postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

FROM ${POSTGRES_IMAGE} AS pgvector-builder

ARG PGVECTOR_VERSION=0.8.2
ARG PGVECTOR_SHA256=69f4019389af05dc1c9548deb8628e62878e6e207c03907f2b8af2016472cdaa

RUN apk add --no-cache --virtual .pgvector-build-deps \
      build-base \
      ca-certificates \
      curl \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --retry 4 --retry-all-errors --retry-delay 2 \
      --connect-timeout 20 --max-time 180 \
      --output /tmp/pgvector.tar.gz \
      "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" \
    && echo "${PGVECTOR_SHA256}  /tmp/pgvector.tar.gz" | sha256sum -c - \
    && mkdir /tmp/pgvector \
    && tar --extract --gzip --file /tmp/pgvector.tar.gz \
      --directory /tmp/pgvector --strip-components=1 \
    && make -C /tmp/pgvector OPTFLAGS="" with_llvm=no \
    && make -C /tmp/pgvector install \
      DESTDIR=/tmp/pgvector-install with_llvm=no

FROM ${POSTGRES_IMAGE}

LABEL org.opencontainers.image.source="https://github.com/pgvector/pgvector" \
      org.opencontainers.image.version="0.8.2"

COPY --from=pgvector-builder /tmp/pgvector-install/ /
