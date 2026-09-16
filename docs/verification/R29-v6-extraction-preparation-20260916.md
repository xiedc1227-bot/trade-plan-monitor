# R29 plan-extract-v6 offline preparation record

Canonical English; `R29-v6-extraction-preparation-20260916.zh-CN.md` is the equivalent Chinese review copy. Proposal `R29-20260917-V6-LITERAL-ACCEPTANCE-1`; run `r29-20260917-a`. Status **OFFLINE_PREPARATION_COMPLETE / LIVE_NOT_RUN / CLAIM_UNCONSUMED / ZERO_AI / ZERO_MARKET / EXACT_APPROVAL_PENDING**.

## Prepared result

R29 now has a fail-closed one-shot candidate that selects `plan-extract-v6` without changing the repository default or real configuration. It reuses the production provider, extraction, strict schema, server mapping validation, v2 diagnostic sidecar and literal oracle. The only shared change makes the transport prompt-byte ceiling configurable while leaving its `19,000` default unchanged; R29 sets the exact frozen v6 size `19,359`, and the prompt hash and full request body remain mandatory.

The execution gate permits one `LITERAL` AI POST, zero retries, zero market calls, a 30-second provider timeout, a 45-second total boundary and at most 15 seconds of cleanup. The first terminal result stops the run. Receipt uncertainty, model mismatch, non-stop finish, provider/timeout, JSON/schema/mapping failure, oracle mismatch, review-receipt mismatch, isolation failure or cleanup failure cannot trigger resubmission.

## Exact egress package

The ignored local review directory is `data/r29-v6-extraction-review/`. It contains the exact material JSON, complete English and Chinese review copies, and manifest. The package SHA-256 is `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9`.

| File | SHA-256 |
|---|---|
| `egress-material.json` | `e017fc3d453c943a020cb438644ae05e41f1738d8055ddd4d8c73404187b5bc1` |
| `egress-review.md` | `aadffd35eda02ef3cfe238ed00abd5215fc8c0ade48f012dce19e22055d2b030` |
| `egress-review.zh-CN.md` | `28e493b5a50f31ca20f3d8db88924b62e37f6cd6a2b37a33fcb85e87a69f38b8` |
| `manifest.json` | `ef8d955294d7bac991f104604243887cb4a180968d3e209bec5c956c0f662240` |

The package displays the complete synthetic source and complete v6 sole user prompt without translating either. It also displays the request fields, destination, one-call boundary, v5/v6 prompt hashes, changed rule summary and conservative current cost estimate. It excludes credentials, complete configuration, provider output, response headers, exception text and direct IP addresses.

## Offline verification

- The R29 focused suite contributes `16` collected cases and all `16` passed within the combined regression run.
- The combined R25/R26/R27/R28, provider, extraction, diagnostics and explicit-review group ran `138` cases: `137` passed and one R25 preflight case failed only because an isolated Git worktree intentionally lacks ignored `config/app.yaml`. No real configuration was copied to make that test pass.
- An additional R14-inclusive run produced `52` passes and two unrelated failures: the pre-existing R14 guard test omits its already-required `temperature=0`, and the isolated worktree lacks ignored installed Web assets. R29 did not modify either condition.
- Ruff check passed for all three changed Python files. Ruff format check passed for the two new Python files. The pre-existing R14 file has broader formatter drift outside the four-line R29 change, so it was not mechanically reformatted.
- `git diff --check` passed, with only Git's Windows line-ending notice for the existing R14 file.
- The dry-run preflight reports `materialMatchesFrozenV6=true`, `reviewPackageMatchesCandidate=true`, `freshClaimAvailable=true`, `configCopiedIntoWorktree=false`, and `ready=false`.
- One existing Starlette/httpx deprecation warning remains.

## Actual gate state

No DeepSeek or market request was made, no account endpoint was probed, no claim was created, no database was created, and no production/real configuration was changed. The isolated worktree currently has no configuration source, and the code had not yet been committed when the dry-run snapshot was captured. The proposed execution date is `2026-09-17`; it is not an authorization.

The only next action is human review of the exact local package. Because v6 changes prompt bytes, the prior v5 approvals do not apply. Execution remains blocked until the user explicitly approves one send of the displayed package to `POST https://api.deepseek.com/chat/completions`, acknowledges the possible charge, and all preflight gates—including a fresh official route/price recheck and explicit read-only configuration path—are green.
