FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY revettr/ revettr/
COPY revettr_mcp/ revettr_mcp/
COPY README.md .

RUN pip install --no-cache-dir ".[mcp]"

RUN useradd -r -s /bin/false appuser
USER appuser

ENV REVETTR_URL=https://revettr.com

EXPOSE 8081

CMD ["python", "-m", "revettr_mcp.serve_http"]
