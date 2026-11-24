FROM scratch
ARG VERSION=0.1.0-rc.1
ARG REVISION=uncommitted
LABEL org.nethserver.rootfull="1" \
      org.nethserver.max-per-node="1" \
      org.nethserver.min-core="3.25.1" \
      org.nethserver.images="" \
      org.opencontainers.image.source="https://github.com/Platypuschan/ns8-no-s81c" \
      org.opencontainers.image.title="No s81c (local fonts)" \
      org.opencontainers.image.description="Host-local IBM Plex fonts for Cluster Admin" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"
COPY imageroot /imageroot
COPY ui /ui
