FROM postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

RUN apk add --no-cache openssl \
    && addgroup -g 10001 backup \
    && adduser -D -u 10001 -G backup backup

COPY --chown=backup:backup backup.sh /usr/local/bin/backup.sh
RUN chmod 0555 /usr/local/bin/backup.sh

USER backup

ENTRYPOINT ["/usr/local/bin/backup.sh"]
