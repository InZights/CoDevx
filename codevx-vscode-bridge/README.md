# CoDevx Copilot Bridge — VS Code Extension

A VS Code extension that bridges **CoDevx agent LLM calls** to **GitHub Copilot** via the VS Code Language Model API (`vscode.lm`).

When this extension is running, CoDevx's 8 agents (Architect, Frontend Dev, Backend Dev, etc.) send their prompts to **GitHub Copilot** instead of — or alongside — OpenAI. The agents get the full power of Copilot's models (GPT-4o, Claude 3.5 Sonnet, o1, etc.) with your existing Copilot subscription — no extra API key needed.

## How it works

```
CoDevx agent_mesh.py
  └── llm_call("Architect", prompt)
        └── POST http://localhost:8001/chat   ← bridge HTTP endpoint
              └── vscode.lm.selectChatModels()
                    └── GitHub Copilot (GPT-4o / Claude / o1)
                          └── response text → back to agent_mesh
```

## Setup

### 1. Install the extension

**From source (development):**
```bash
cd codevx-vscode-bridge
npm install
npm run compile
```
Then press `F5` in VS Code to launch the Extension Development Host, or:
```bash
npm run package   # creates codevx-vscode-bridge-1.0.0.vsix
code --install-extension codevx-vscode-bridge-1.0.0.vsix
```

### 2. Configure CoDevx

In your `.env` file (copy from `.env.example`):

```env
# Route all agent LLM calls through GitHub Copilot
LLM_PROVIDER=copilot
COPILOT_BRIDGE_URL=http://localhost:8001

# Keep OPENAI_API_KEY for fallback (optional)
# OPENAI_API_KEY=sk-...
```

### 3. Start CoDevx

```bash
python agent_mesh.py
```

The bridge starts automatically when VS Code opens. You'll see:
- A status bar item: `⚙ CoDevx Bridge :8001`
- An info notification confirming the port

### 4. Submit a task

Via Discord, WhatsApp, REST API, or IDE MCP — agents now use Copilot.

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `codevxBridge.port` | `8001` | Port for the bridge HTTP server |
| `codevxBridge.model` | `gpt-4o` | Preferred Copilot model family |
| `codevxBridge.autoStart` | `true` | Auto-start when VS Code opens |

## Bridge API

The extension runs a local HTTP server accessible only on `127.0.0.1`.

### `GET /health`
```json
{ "status": "ok", "bridge": "codevx-vscode-copilot", "version": "1.0.0" }
```

### `GET /models`
Lists available Copilot models on your account.

### `POST /chat`
```json
{
  "agent": "Architect",
  "system": "<agent system prompt>",
  "user": "<task message>",
  "model": "gpt-4o"
}
```
Response:
```json
{
  "content": "<LLM output>",
  "model": "GPT-4o",
  "vendor": "copilot"
}
```

## Provider fallback

If `LLM_PROVIDER=copilot` and the bridge is unreachable, `agent_mesh.py` falls back to OpenAI (if `OPENAI_API_KEY` is set) or simulation mode.

## Requirements

- VS Code 1.90+
- GitHub Copilot extension installed and signed in
- GitHub Copilot Individual, Business, or Enterprise subscription
