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
  ide?: string;       // "copilot" | "cursor" | "antigravity" — which IDE chatbot is being consulted
  include_workspace?: boolean; // if true, attach open file context to the prompt
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
  outputChannel.appendLine(`[Bridge] Endpoints: /health  /models  /chat  /workspace-context`);
  outputChannel.appendLine(`[Bridge] Brain config:     set LLM_PROVIDER=copilot  in CoDevx .env`);
  outputChannel.appendLine(`[Bridge] IDE tools config: set IDE_TOOLS_ENABLED=true in CoDevx .env`);
  vscode.window.showInformationMessage(
    `CoDevx Bridge running on :${port} — agents can now consult Copilot/Cursor as IDE tools.`
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
    const models = await vscode.lm.selectChatModels({ vendor: "copilot" }).catch(() => []);
    sendJson(res, 200, {
      status: "ok",
      bridge: "codevx-vscode-copilot",
      version: "1.1.0",
      capabilities: ["copilot", "cursor", "workspace-context"],
      copilot_available: models.length > 0,
      active_models: models.slice(0, 3).map((m) => ({ id: m.id, family: m.family })),
      workspace_files: vscode.workspace.textDocuments.length,
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

  // ── Workspace context endpoint ────────────────────────────────────────────
  // Returns snippets of files currently open in VS Code so agents can use them.
  if (req.method === "GET" && (url === "/workspace-context" || url.startsWith("/workspace-context?"))) {
    const openDocs = vscode.workspace.textDocuments
      .filter((d) => !d.isUntitled && d.uri.scheme === "file")
      .slice(0, 10); // cap at 10 files to stay within token budget
    const files = openDocs.map((d) => ({
      path: vscode.workspace.asRelativePath(d.uri),
      language: d.languageId,
      lines: d.lineCount,
      // First 120 lines of each file as preview context
      preview: d.getText().split("\n").slice(0, 120).join("\n"),
    }));
    sendJson(res, 200, { workspace_files: files });
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

    const { agent = "Unknown", system = "", user = "", model, ide = "copilot", include_workspace = false } = payload;
    if (!user) {
      sendJson(res, 400, { error: "'user' field is required" } as ErrorResponse);
      return;
    }

    // Optionally enrich prompt with currently-open workspace file context
    let enrichedUser = user;
    if (include_workspace) {
      const openDocs = vscode.workspace.textDocuments
        .filter((d) => !d.isUntitled && d.uri.scheme === "file")
        .slice(0, 5);
      if (openDocs.length) {
        const wsContext = openDocs
          .map((d) => `// ${vscode.workspace.asRelativePath(d.uri)}\n${d.getText().slice(0, 800)}`)
          .join("\n\n---\n\n");
        enrichedUser = `${user}\n\n=== Currently open workspace files (IDE context) ===\n${wsContext}`;
        outputChannel.appendLine(`[Bridge] Attached ${openDocs.length} workspace file(s) to prompt.`);
      }
    }

    outputChannel.appendLine(`[Bridge][${ide.toUpperCase()}] ${agent} → model=${model ?? "default"}`);

    try {
      const result = await callCopilot(system, enrichedUser, model);
      outputChannel.appendLine(`[Bridge][${ide.toUpperCase()}] ${agent} ← ${result.model} (${result.content.length} chars)`);
      sendJson(res, 200, { ...result, ide });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      outputChannel.appendLine(`[Bridge][ERROR][${ide.toUpperCase()}] ${agent}: ${msg}`);
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
