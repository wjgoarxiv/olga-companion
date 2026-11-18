"""Single typed public-result schema catalog for the agent tool registry."""

from typing import Final

from .case_tool_response_schemas import CASE_TOOL_RESPONSE_SCHEMAS
from .case_transaction_response_schemas import CASE_TRANSACTION_RESPONSE_SCHEMAS
from .simulation_patrol_schemas import SIMULATION_PATROL_RESPONSE_SCHEMAS
from .tool_artifact_schemas import TOOL_RESPONSE_SCHEMAS as ARTIFACT_RESPONSE_SCHEMAS

TOOL_RESPONSE_SCHEMAS: Final = {
    **ARTIFACT_RESPONSE_SCHEMAS,
    **CASE_TOOL_RESPONSE_SCHEMAS,
    **CASE_TRANSACTION_RESPONSE_SCHEMAS,
    **SIMULATION_PATROL_RESPONSE_SCHEMAS,
}
