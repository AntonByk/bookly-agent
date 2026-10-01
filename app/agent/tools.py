"""Model-facing tool contracts.

The model will only receive a subset based on session scope and conversational state.
There is intentionally no create_return or issue_refund model tool.
"""

PUBLIC_TOOLS = [
    {
        "type": "function",
        "name": "search_knowledge",
        "description": "Search Bookly public help-centre content for information relevant to the customer's question.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]

VERIFIED_TOOLS = [
    {
        "type": "function",
        "name": "list_orders",
        "description": "List recent orders owned by the authenticated customer.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_tracking",
        "description": "Get authoritative tracking events for one order owned by the authenticated customer.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "check_return_eligibility",
        "description": "Ask Commerce whether an item is eligible for a return for a normalized reason category.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "reason_category": {"type": "string", "enum": ["changed_mind", "damaged"]},
            },
            "required": ["order_id", "item_id", "reason_category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "propose_return",
        "description": "Create a pending return proposal for UI confirmation. This does not execute a return.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "item_id": {"type": "string"},
                "reason_category": {"type": "string", "enum": ["changed_mind", "damaged"]},
            },
            "required": ["order_id", "item_id", "reason_category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]
