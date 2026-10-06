"""Tool definitions for the D4 banking agent, shared by the Arabic gate (and later D4 itself)."""

TOOLS = {
    "send_otp": {"description": "Send a one-time password to the customer's registered phone. Required before any account or card action.",
                 "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}},
    "verify_otp": {"description": "Verify the OTP code the customer provides.",
                   "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}, "code": {"type": "string"}},
                                  "required": ["customer_id", "code"]}},
    "get_balance": {"description": "Get the verified customer's account balance.", "parameters": {"type": "object", "properties": {}}},
    "block_card": {"description": "Block one of the verified customer's cards.",
                   "parameters": {"type": "object", "properties": {"last4": {"type": "string"},
                                                                   "reason": {"type": "string", "enum": ["lost", "stolen", "fraud", "customer_request"]}},
                                  "required": ["last4", "reason"]}},
    "create_ticket": {"description": "Log a complaint or service ticket.",
                      "parameters": {"type": "object", "properties": {"category": {"type": "string"}, "description": {"type": "string"}},
                                     "required": ["category", "description"]}},
    "handoff_to_human": {"description": "Transfer the conversation to a human customer-service agent.",
                         "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    "search_kb": {"description": "Search the bank's knowledge base of products and procedures.",
                  "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
}


def openai_tools(names: list[str]) -> list[dict]:
    return [{"type": "function", "function": {"name": n, **TOOLS[n]}} for n in names]
