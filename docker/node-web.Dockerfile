# Arbeitsumgebung für Web-Aufgaben. Vorgewärmt, damit nicht jeder Lauf dieselbe
# Grundinstallation wiederholt — bei einem Sweep über zwölf Modelle summiert sich das.
FROM node:22-slim

# coreutils liefert `timeout`, mit dem die Sandbox Einzelbefehle wirklich beendet.
RUN apt-get update \
    && apt-get install -y --no-install-recommends coreutils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Der Arbeitsbereich gehört dem unprivilegierten Nutzer `node`, der im Image bereits
# existiert. Kein Host-Mount — alles bleibt im Container.
RUN mkdir -p /workspace && chown node:node /workspace

USER node
WORKDIR /workspace

ENV npm_config_update_notifier=false \
    npm_config_fund=false \
    npm_config_audit=false \
    CI=true

CMD ["sleep", "infinity"]
