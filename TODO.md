# TODO

## LangSmith token split (input vs output)

**File:** `llm_apipool/langchain_wrapper.py`

**Problem:** LangSmith expects separate `input_tokens` and `output_tokens` counts for accurate cost and usage dashboards. The aggregator currently only reports a combined `tokens_used` total from each provider response. As a workaround, `usage_metadata` and `token_usage` in `llm_output` are populated with `input_tokens=0` and `output_tokens=total`, which means LangSmith shows all tokens as output tokens.

**Proper fix:** Each provider's response handler in `providers/` needs to return separate prompt and completion token counts. These should be surfaced through the `CompletionResult` dataclass and then mapped to `input_tokens`/`output_tokens` in the LangChain wrapper.

**Affected providers:** All - Groq, Cerebras, Mistral, OpenRouter all include token split in their API responses but it is not currently plumbed through.

**Impact:** Cosmetic - total token count is accurate. Only the input/output breakdown is wrong in LangSmith traces.
