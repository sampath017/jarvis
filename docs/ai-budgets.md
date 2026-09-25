# AI spending allowance

Production uses one **Rs 20/day AI allowance**, reset at midnight IST. There is no daily token or model-call ceiling. The per-minute guard remains 15 requests/minute. Local testing retains finite token/call guardrails but uses the same spending allowance.

OpenRouter bills USD. Jarvis currently budgets at Rs 96.544/USD (verified 2026-10-06), so its daily provider-usage allowance is **approximately USD 0.20716**. This conversion is explicit in health metadata; payment fees, taxes, Cloud Run, Firebase, and Maps are outside this AI allowance.

Cloud Run uses transactional Firestore ledgers at `users/{uid}/ai_usage/{IST-date}`, shared across instances and deployments. It reserves estimated input and maximum output cost before each model call, then settles using OpenRouter's reported `usage.cost`. Cached and reasoning usage is included in provider-reported cost. Settlement is idempotent and uses the call's starting day even if completion crosses midnight. Storage errors return 503; they never silently reset usage.

Unknown transport outcomes retain their reservation until the next day. Missing billing data keeps at least the reserved cost. Model prices are bounded with OpenRouter `provider.max_price`: GLM 5.3 Flash USD 0.15 input / 0.50 output per million; Gemini 3.8 Flash USD 0.75 / 3.75. Unknown models fail closed until their pricing policy is added. No change to reasoning effort or generation allowance.

Preflight token estimates, especially native file input, are not exact quotes. A single request can cost more than its estimate. The user explicitly chose backend-only enforcement; OpenRouter account key limits stay unchanged. The backend stops new model calls when spent plus reserved cost would exceed the allowance, but a provider charge above an estimated input reservation can overshoot by one in-flight call. Bank charges and exchange-rate changes are not included in this fixed-conversion allowance. Previously process-only usage is not automatically migrated into the ledger.

On 2026-10-06, the old 150,000-token guard rejected requests with 131,361 tokens used because estimated input plus 16,384 maximum output did not fit. A later Cloud Run instance started at zero, allowing more prompts. New errors identify remaining rupees, the requested reservation, the exact reset date, and distinguish app allowance, provider credits, and device location failures.
