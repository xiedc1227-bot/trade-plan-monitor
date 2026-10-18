"""A source restriction on a subset cannot grant whole-position exit withdrawal."""


def risk_scope_issue(operation):
    if operation.target != "risk_branches":
        return None
    scope = operation.scope_assessment
    if scope == "PARTIAL_RULE":
        return (None if operation.scope_change is not None
                else "UPDATE_SCOPE_DIRECTION_REQUIRED")
    if scope == "UNCLEAR":
        return "UPDATE_SOURCE_AMBIGUITY"
    if operation.action != "REVOKE":
        return None
    return {
        None: "UPDATE_WITHDRAWAL_SCOPE_REQUIRED",
        "ENTIRE_RULE": None,
        "CONTEXT_ONLY": "UPDATE_WITHDRAWAL_CONTEXT_ONLY",
    }[scope]
