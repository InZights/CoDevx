# ─────────────────────────────────────────────────
# Python backend (runs on host, not in Docker,
# so it can reach GitHub Copilot CLI and local FS)
# ─────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_mesh.py .
COPY command_center.html .
COPY zeroclaw_squad.yaml .

EXPOSE 8000

CMD ["python", "agent_mesh.py"]
