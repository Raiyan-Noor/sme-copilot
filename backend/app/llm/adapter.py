"""The single LLM adapter. OpenAI primary, Gemini Flash fallback via its OpenAI-compatible endpoint.

Falls back on budget cap (LLM_BUDGET_USD), insufficient_quota, 429, 5xx and timeouts. Logs provider and model
for every call (invariant 7). This is the only module allowed to import openai.
"""
