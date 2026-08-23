FROM minio/mc:RELEASE.2025-08-13T08-35-41Z AS minio_client

FROM postgres:17-alpine

COPY --from=minio_client /usr/bin/mc /usr/local/bin/mc
COPY backup-entrypoint.sh backup.sh restore.sh /usr/local/bin/

RUN apk add --no-cache openssl \
    && chmod 0555 \
    /usr/local/bin/backup-entrypoint.sh \
    /usr/local/bin/backup.sh \
    /usr/local/bin/restore.sh

ENTRYPOINT ["/usr/local/bin/backup-entrypoint.sh"]
CMD ["backup"]
