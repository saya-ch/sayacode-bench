FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN git init -q \
    && git config user.name "Synthetic smoke" \
    && git config user.email "smoke@example.invalid" \
    && printf 'Synthetic infrastructure fixture, not a public benchmark.\n' > README.md \
    && git add README.md \
    && GIT_AUTHOR_DATE='2020-01-01T00:00:00Z' GIT_COMMITTER_DATE='2020-01-01T00:00:00Z' \
       git commit -q -m 'Synthetic fixture baseline'
