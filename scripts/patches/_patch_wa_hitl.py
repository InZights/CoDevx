"""Patch: Add 'approve/reject arch' commands to WhatsApp webhook."""
from pathlib import Path

MESH = Path(__file__).parent / "agent_mesh.py"
src = MESH.read_text(encoding="utf-8")

OLD = (
    'await wa_send(sender, "No pending plan to reject.")\n'
    "\n"
    "    else:\n"
    "        await wa_send(\n"
    "            sender,\n"
    '            "AI Dev Team Commands:\\n\\n"\n'
    '            "order <task> -- start a new pipeline\\n"\n'
    '            "approve -- approve the pending plan\\n"\n'
    '            "reject -- reject the pending plan",\n'
    "        )"
)

NEW = (
    'await wa_send(sender, "No pending plan to reject.")\n'
    "\n"
    "    elif body_lower.startswith(\"approve arch\") or body_lower.startswith(\"reject arch\"):\n"
    "        # Human-in-the-loop architecture gate (HUMAN_GATE_ENABLED=true)\n"
    "        parts_wa  = Body.strip().split()\n"
    '        action_wa = parts_wa[0].lower()   # "approve" or "reject"\n'
    '        tid_arg   = parts_wa[2] if len(parts_wa) > 2 else _gate_task_map.get("current", "")\n'
    "        gate      = _pipeline_gates.get(tid_arg)\n"
    "        if gate and not gate.is_set():\n"
    '            if action_wa == "approve":\n'
    "                gate.set()\n"
    '                await wa_send(sender, f"\u2705 Architecture approved for task {tid_arg}. Coding begins...")\n'
    '                add_log(f"[HITL][WhatsApp] Architecture approved by {sender} \u2014 task {tid_arg}")\n'
    "            else:\n"
    '                SYSTEM_STATE[f"_gate_rejected_{tid_arg}"] = True\n'
    "                gate.set()\n"
    '                await wa_send(sender, f"\u274c Architecture rejected for task {tid_arg}. Pipeline aborted.")\n'
    '                add_log(f"[HITL][WhatsApp] Architecture rejected by {sender} \u2014 task {tid_arg}")\n'
    "        else:\n"
    "            await wa_send(sender, f\"\u26a0\ufe0f No open architecture gate for task '{tid_arg}'.\")\n"
    "\n"
    "    else:\n"
    "        await wa_send(\n"
    "            sender,\n"
    '            "AI Dev Team Commands:\\n\\n"\n'
    '            "order <task>              \u2014 start a new pipeline\\n"\n'
    '            "approve                   \u2014 approve the pending plan\\n"\n'
    '            "reject                    \u2014 reject the pending plan\\n"\n'
    '            "approve arch <task_id>    \u2014 approve architecture (HITL gate)\\n"\n'
    '            "reject arch <task_id>     \u2014 reject architecture (HITL gate)",\n'
    "        )"
)

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    MESH.write_text(src, encoding="utf-8")
    print("✅ WhatsApp arch gate commands added successfully")
else:
    print("❌ Anchor string not found in agent_mesh.py")
    # Debug: show nearby text
    idx = src.find("No pending plan to reject")
    if idx >= 0:
        print("Nearby text:")
        print(repr(src[idx:idx+400]))
