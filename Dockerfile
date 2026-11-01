FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-agent.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-agent.txt \
 && playwright install --with-deps chromium
COPY . .
# pre-fetch the pinned Notion MCP server so first run isn't a cold npx download
RUN npx -y @notionhq/notion-mcp-server@2.6.1 --help >/dev/null 2>&1 || true
CMD ["python", "-m", "agent", "run"]
