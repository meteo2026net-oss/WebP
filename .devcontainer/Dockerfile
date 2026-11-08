# Keep the upstream Dev Container image, but remove the stale Yarn APT
# source before Dev Container Features run apt-get update.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

USER root

RUN set -eu; \
    for source in /etc/apt/sources.list /etc/apt/sources.list.d/*; do \
      [ -f "$source" ] || continue; \
      if grep -q "dl.yarnpkg.com/debian" "$source"; then \
        echo "Removing stale Yarn APT source: $source"; \
        rm -f "$source"; \
      fi; \
    done
