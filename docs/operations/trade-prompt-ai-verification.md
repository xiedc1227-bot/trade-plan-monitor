# Real AI verification of generated plans

This procedure is separate from the reusable generation prompt. Run it only when the user explicitly requests real provider verification. Generation alone supplies no permission to save, approve, activate or execute a plan.

1. Use the project-configured provider, exact requested model and existing budgets. For the cross-symbol sample checks the selected model is `deepseek-flash`; limits are 50,000 input characters, 4096 output tokens, 30 seconds and 2 maximum retries. Never print credentials or increase budgets to avoid failure.
2. Generate A/B from the exact README prompt and supplied facts. Send only unchanged A to the real extraction function, preserving original requests, responses, hashes and results. Do not strip prefixes, fill fields, remove bindings or repair output. Keep Schema, source review and all safety validation intact.
3. Check extraction status, candidate structure, every source clause and binding, issues, assumptions and warnings. Count BUY/SELL, risk branches and reminders against the actual requested policy; valid JSON or `finish_reason=stop` alone is insufficient. Inspect B separately for invented facts, redundant confirmations and incorrect capability claims.
4. Missing required limits or unsupported necessary dependencies must block complete policy generation, without fake values, weakened rules or unauthorized reminder substitutes. A negative source is exactly `暂不提供可导入正文。` and is not submitted as a plan for extraction.
5. Preserve and report failures and prose deviations. Diagnose before revising and revalidating; do not retry unchanged prompts until a preferred result appears. Do not substitute a previous prompt's success for this version.
6. Record actual validation outside the model-generated source/appendix; generation cannot claim a future extraction already passed. Compare read-only before/after state when required. Successful verification does not save a draft, confirm review, activate a plan, execute a trade or mutate actual/simulated inventory.

Synthetic cross-symbol tests establish only the tested software contracts. English/Chinese prompt parity can be checked separately; state explicitly which language was sent to the provider.
