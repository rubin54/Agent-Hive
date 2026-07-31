# Checking environment for functional checks.
#
# Deliberately its own image next to the sandbox: the subject under test must not be able to
# touch its measuring instrument. If Playwright lived in the same container, a model could
# tamper with the check — a non-starter for a benchmark.
FROM mcr.microsoft.com/playwright:v1.49.1-noble

WORKDIR /checker

# Installed at build time so the check run itself needs no network access.
RUN npm init -y >/dev/null \
    && npm install --no-fund --no-audit @playwright/test@1.49.1

ENV CI=true \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

CMD ["sleep", "infinity"]
