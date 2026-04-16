from __future__ import annotations

# Skill protocol keywords
TOOL_SKILL_TOOL = "skill_tool"
ARG_NAME = "name"
ARG_INPUT = "input"
FM_ALLOWED_TOOLS = "allowed-tools"
SKILL_FILENAME = "SKILL.md"

# Skill tool runtime error templates
ERR_SKILL_TOOL_NAME_EMPTY = "ERROR: skill_tool requires non-empty tool name"
ERR_SKILL_TOOL_INPUT_NOT_OBJECT = "ERROR: skill_tool.input must be a JSON object"
ERR_SKILL_TOOL_NOT_ACTIVATED = "ERROR: skill_tool requires an activated skill. Read a skill SKILL.md first."
ERR_SKILL_TOOL_NOT_ALLOWED_TEMPLATE = (
    "ERROR: skill_tool '{tool_name}' is not allowed by active skill "
    "{skill_name}. allowed-tools={allowed_tools}"
)
ERR_SKILL_TOOL_SCRIPT_NOT_CONFIGURED_TEMPLATE = (
    "ERROR: skill_tool script is not configured for tool '{tool_name}' in skill {skill_name}"
)
