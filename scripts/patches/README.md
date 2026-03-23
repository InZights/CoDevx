# scripts/patches/

One-shot patch scripts created during development to incrementally add features to `agent_mesh.py`.

| Script | What it does |
|--------|-------------|
| `_patch_mcp.py` | Added MCP server endpoints |
| `_patch_llm_provider.py` | Added `LLM_PROVIDER` routing |
| `_patch_ide_tools.py` | Wired `consult_ide_chatbot()` into pipeline stages |
| `_patch_multillm.py` | Replaced OpenAI-only client with LiteLLM universal router |
| `_patch_langgraph.py` | Added LangGraph QA/Security subgraphs + HITL gate |
| `_patch_wa_hitl.py` | Added `approve/reject arch` WhatsApp commands |

These scripts are idempotent (they check before patching) and are kept for reference.
They are **not** needed for normal deployment — `agent_mesh.py` already includes all their changes.
