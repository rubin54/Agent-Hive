# Working environment for web tasks. Pre-warmed so that not every run repeats the same
# base installation — across a sweep of twelve models that adds up.
FROM node:22-slim

# coreutils provides `timeout`, which the sandbox uses to really terminate commands.
RUN apt-get update \
    && apt-get install -y --no-install-recommends coreutils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The workspace belongs to the unprivileged `node` user that already exists in the image.
# No host mount — everything stays inside the container.
RUN mkdir -p /workspace && chown node:node /workspace

USER node
WORKDIR /workspace

ENV npm_config_update_notifier=false \
    npm_config_fund=false \
    npm_config_audit=false \
    CI=true

CMD ["sleep", "infinity"]
