"""One current extraction prompt; retired version identifiers remain audit metadata only."""

from typing import Final

# Historical audit labels, not selectable extraction contracts.
PLAN_EXTRACTION_PROMPT_V1: Final = "plan-extract-v1"
PLAN_EXTRACTION_PROMPT_V2: Final = "plan-extract-v2"
PLAN_EXTRACTION_PROMPT_V3: Final = "plan-extract-v3"
PLAN_EXTRACTION_PROMPT_V4: Final = "plan-extract-v4"
PLAN_EXTRACTION_PROMPT_V5: Final = "plan-extract-v5"
PLAN_EXTRACTION_PROMPT_V6: Final = "plan-extract-v6"
PLAN_EXTRACTION_PROMPT_VERSION: Final = "plan-extract-v11"
MAX_SOURCE_TEXT_CHARS: Final = 150_000


def build_plan_extraction_prompt(source_text, *, prompt_version=PLAN_EXTRACTION_PROMPT_VERSION):
    from trade_plan_monitor.ai.plan_extraction import build_current_plan_prompt

    if prompt_version != PLAN_EXTRACTION_PROMPT_VERSION:
        raise ValueError("Historical extraction contracts are read-only audit metadata")
    return build_current_plan_prompt(source_text)
