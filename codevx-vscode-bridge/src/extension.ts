import * as vscode from "vscode";
import * as http from "http";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatRequest {
  agent: string;      // e.g. "Architect", "Backend Dev"
  system: string;     // agent system prompt
  user: string;       // user / task message
  temperature?: number;
  model?: string;     // override model family
}

interface ChatResponse {
  content: string;
  model: string;
  vendor: string;
  tokens_used?: number;
}

interface ErrorResponse {
  error: string;
  code?: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let server: http.Server | undefined;
let statusBar: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  outputChannel = vscode.window.createOutputChannel("CoDevx Copilot Bridge");

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = "codevx-bridge.status";
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand("codevx-bridge.start", () => startServer(context)),
    vscode.commands.registerCommand("codevx-bridge.stop", stopServer),
    vscode.commands.registerCommand("codevx-bridge.status", showStatus),
  );

  // Auto-start if configured (default: true)
  const cfg = vscode.workspace.getConfiguration("codevxBridge");
  if (cfg.get<boolean>("autoStart", true)) {
    await startServer(context);
  }
}

export function deactivate(): void {
  stopServer();
}

// ---------------------------------------------------------------------------
// Server lifecycle
// ---------------------------------------------------------------------------

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  if (server) {
    outputChannel.appendLine("[Bridge] Already running.");
    return;
  }

  const cfg = vscode.workspace.getConfiguration("codevxBridge");
  const port = cfg.get<number>("port", 8001);

  server = http.createServer((req, res) => {
    handleRequest(req, res).catch((err: Error) => {
      outputChannel.appendLine(`[Bridge][ERROR] Unhandled: ${err.message}`);
      if (!res.writableEnded) {
        sendJson(res, 500, { error: "Internal bridge error" } as ErrorResponse);
      }
    });
  });

  await new Promise<void>((resolve, reject) => {
    server!.listen(port, "127.0.0.1", () => resolve());
    server!.once("error", reject);
  });

  context.subscriptions.push({ dispose: stopServer });

  updateStatusBar(port, true);
  outputChannel.appendLine(`[Bridge] Started on http://127.0.0.1:${port}`);
  outputChannel.appendLine(`[Bridge] Set COPILOT_BRIDGE_URL=http://localhost:${port} in CoDevx .env`);
  outputChannel.appendLine(`[Bridge] Set LLM_PROVIDER=copilot in CoDevx .env`);
  vscode.window.showInformationMessage(
    `CoDevx Copilot Bridge running on port ${port}. Set LLM_PROVIDER=copilot in .env.`
  );
}

function stopServer(): void {
  if (server) {
    server.close();
    server = undefined;
    updateStatusBar(0, false);
    outputChannel.appendLine("[Bridge] Stopped.");
  }
}

// ---------------------------------------------------------------------------
// HTTP request handler
// ---------------------------------------------------------------------------

async function handleRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse
): Promise<void> {
  const url = req.url ?? "/";

  // ── Health check ──────────────────────────────────────────────────────────
  if (req.method === "GET" && url === "/health") {
    sendJson(res, 200, {
      status: "ok",
      bridge: "codevx-vscode-copilot",
      version: "1.0.0",
    });
    return;
  }

  // ── Models list ───────────────────────────────────────────────────────────
  if (req.method === "GET" && url === "/models") {
    try {
      const models = await vscode.lm.selectChatModels();
      sendJson(res, 200, {
        models: models.map((m) => ({
          id: m.id,
          name: m.name,
          vendor: m.vendor,
          family: m.family,
          maxInputTokens: m.maxInputTokens,
        })),
      });
    } catch (err: unknown) {
      sendJson(res, 503, { error: "Copilot unavailable" } as ErrorResponse);
    }
    return;
  }

  // ── Chat endpoint ─────────────────────────────────────────────────────────
  if (req.method === "POST" && url === "/chat") {
    const body = await readBody(req);
    let payload: ChatRequest;
    try {
      payload = JSON.parse(body) as ChatRequest;
    } catch {
      sendJson(res, 400, { error: "Invalid JSON body" } as ErrorResponse);
      return;
    }

    const { agent = "Unknown", system = "", user = "", model } = payload;
    if (!user) {
      sendJson(res, 400, { error: "'user' field is required" } as ErrorResponse);
      return;
    }

    outputChannel.appendLine(`[Bridge] ${agent} → Copilot (model=${model ?? "default"})`);

    try {
      const result = await callCopilot(system, user, model);
      outputChannel.appendLine(`[Bridge] ${agent} ← ${result.model} (${result.content.length} chars)`);
      sendJson(res, 200, result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      outputChannel.appendLine(`[Bridge][ERROR] ${agent}: ${msg}`);
      sendJson(res, 503, { error: msg, code: "COPILOT_ERROR" } as ErrorResponse);
    }
    return;
  }

  sendJson(res, 404, { error: "Not found" } as ErrorResponse);
}

// ---------------------------------------------------------------------------
// Call GitHub Copilot via vscode.lm
// ---------------------------------------------------------------------------

async function callCopilot(
  system: string,
  user: string,
  preferredFamily?: string
): Promise<ChatResponse> {
  const cfg = vscode.workspace.getConfiguration("codevxBridge");
  const family = preferredFamily ?? cfg.get<string>("model", "gpt-4o");

  // Try to get the requested model family, fall back to any available model
  let models = await vscode.lm.selectChatModels({ vendor: "copilot", family });
  if (!models.length) {
    models = await vscode.lm.selectChatModels({ vendor: "copilot" });
  }
  if (!models.length) {
    throw new Error(
      "No GitHub Copilot language models available. " +
      "Ensure GitHub Copilot is installed and you are signed in."
    );
  }

  const model = models[0];

  // Build messages — system prompts go as a User message since LanguageModelChatMessage
  // only offers User and Assistant roles in the public API.
  const messages: vscode.LanguageModelChatMessage[] = [];
  if (system) {
    // Prefix system context as a framing user message
    messages.push(
      vscode.LanguageModelChatMessage.User(
        `[SYSTEM CONTEXT — follow these instructions for the entire conversation]\n\n${system}`
      )
    );
    messages.push(vscode.LanguageModelChatMessage.Assistant("Understood. I will follow those instructions."));
  }
  messages.push(vscode.LanguageModelChatMessage.User(user));

  const tokenSource = new vscode.CancellationTokenSource();

  // 10-minute timeout for complex agent tasks
  const timeout = setTimeout(() => tokenSource.cancel(), 10 * 60 * 1000);

  try {
    const response = await model.sendRequest(messages, {}, tokenSource.token);

    let content = "";
    for await (const chunk of response.text) {
      content += chunk;
    }

    return {
      content,
      model: model.name,
      vendor: model.vendor,
    };
  } finally {
    clearTimeout(timeout);
    tokenSource.dispose();
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk: Buffer) => { data += chunk.toString(); });
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function sendJson(res: http.ServerResponse, status: number, body: object): void {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(json),
    // Allow agent_mesh (same machine) to call the bridge
    "Access-Control-Allow-Origin": "http://localhost:8000",
  });
  res.end(json);
}

function updateStatusBar(port: number, running: boolean): void {
  if (running) {
    statusBar.text = `$(copilot) CoDevx Bridge :${port}`;
    statusBar.tooltip = `CoDevx Copilot Bridge — running on port ${port}\nClick for status`;
    statusBar.backgroundColor = undefined;
  } else {
    statusBar.text = `$(copilot-warning) CoDevx Bridge`;
    statusBar.tooltip = "CoDevx Copilot Bridge — stopped\nClick to see log";
    statusBar.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }
  statusBar.show();
}

function showStatus(): void {
  outputChannel.show(true);
  const cfg = vscode.workspace.getConfiguration("codevxBridge");
  const port = cfg.get<number>("port", 8001);
  outputChannel.appendLine(
    `\n[Bridge] Status check — server ${server ? `running on :${port}` : "stopped"}\n` +
    `  Health: http://127.0.0.1:${port}/health\n` +
    `  Models: http://127.0.0.1:${port}/models\n` +
    `  Chat:   POST http://127.0.0.1:${port}/chat`
  );
}
