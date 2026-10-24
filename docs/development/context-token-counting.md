# Exact history token-count reuse

Long turns append small messages to otherwise stable history. A memo keyed only
by the complete transcript misses on every append and retokenizes unchanged
messages during each projection's pressure check.

For transcripts longer than 32 messages, the LiteLLM provider counts fixed
32-message blocks with native `count_response_tokens=True`, then adds native
empty-transcript response priming once. No tools or tool choice are passed to
this counting boundary. This preserves native message-count semantics rather
than summing estimates or independently primed full prompts.

Block results share the existing 64-entry, locked digest/count LRU with complete
transcript and text results. Keys include model and tokenizer-visible content;
no transcript, token arrays or context snapshot is retained in the memo.
Changed fields, inserted messages, changed models and eviction force recounts.
Failed native counts do not publish partial block results. Small transcripts
retain the original single native count. Cache contention can reduce reuse but
cannot change the result.

Native-tokenizer parity tests cover model families, response priming, tool
arguments, names, Unicode, content blocks, low-detail images, mutation,
insertion/deletion and concurrent reuse. Run these tests when upgrading LiteLLM:
the optimization depends on native message counts being additive without
response priming. Existing estimator identity and fallback behavior are unchanged.

This is a CPU optimization, not a demonstrated fix for controller RSS growth.
It does not change history retention, session-cache eviction, snapshot isolation,
offload admission, context truncation, or exact budget checks.
