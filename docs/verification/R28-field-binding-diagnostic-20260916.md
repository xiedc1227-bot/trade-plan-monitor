# R28 field-binding contract and safe diagnostic verification

Canonical English; `R28-field-binding-diagnostic-20260916.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_COMPLETE / PROSPECTIVE_DIAGNOSTIC_FIXED / V6_CANDIDATE_ONLY / ZERO_EXTERNAL_CALLS**.

## Scope and evidence boundary

R28 investigated the R27 terminal result `INVALID_OUTPUT / schema / SCHEMA / field_bindings[4] / value_error` without replaying R27. It made no DeepSeek POST, market-data call, claim, activation, trade, or business-data write. The retained R27 evidence excludes the raw response and validator message, so R28 cannot identify which historical `FieldBinding` invariant failed. Synthetic failures below prove the former diagnostic collision and the prospective fix; they are not reconstructions of the fifth R27 binding.

## Validator and prompt audit

The `FieldBinding` model enforced six distinct cross-field invariants while Pydantic reported each failure as the same generic `value_error`. The generated JSON Schema does not encode these model validators. `plan-extract-v5` rules 5 and 6 described source attribution, contract restrictions, and structure binding at a high level, but did not state the exact mutually exclusive reference fields, unique clause references and binding identities, complete unit mapping, `STRUCTURE` value restriction, or the absence of durable `user_supplements` from the extraction envelope.

| ID | Enforced invariant | Prospective safe `schemaErrorType` |
|---|---|---|
| R28-FB01 | `clause_ids` contains no duplicate. | `field_binding_clause_ids_not_unique` |
| R28-FB02 | `SOURCE` has non-empty `clause_ids` and null `supplement_id` / `contract_id`. | `field_binding_source_reference_invalid` |
| R28-FB03 | `USER_SUPPLEMENT` has empty `clause_ids`, non-null `supplement_id`, and null `contract_id`. | `field_binding_user_supplement_reference_invalid` |
| R28-FB04 | `CONTRACT` has empty `clause_ids`, null `supplement_id`, and non-null `contract_id`. | `field_binding_contract_reference_invalid` |
| R28-FB05 | `CONTRACT` addresses only a valid technical scalar or a `.rule_id`; the unreachable object path `metadata` is no longer admitted at schema validation. | `field_binding_contract_path_forbidden` |
| R28-FB06 | A `STRUCTURE` binding value is exactly `ALL` or `ANY`. | `field_binding_structure_value_invalid` |

Server mapping validation remains fail-closed after schema validation. It resolves each path against the current typed draft; requires `STRUCTURE` to address a condition object and `VALUE` to address a scalar; checks the exact JSON type/value and path-derived unit; checks SOURCE clause existence, `MAPPED` disposition and reciprocal path; rejects source-treatment trading parameters; checks durable USER_SUPPLEMENT equality; and restricts CONTRACT paths. Missing scalar/structure bindings and non-reciprocal mapped clauses remain server-derived review blockers rather than invented execution semantics.

## Implemented correction

Each `FieldBinding` custom validator now raises a fixed `PydanticCustomError` type. The extraction boundary allowlists only the six fixed types above; any unrecognized custom type remains `other`. It still reads Pydantic errors with input, context, and URL excluded, and neither result serialization nor the sidecar stores exception text or provider content.

The sidecar stays at version `2`: no field was added, removed, or made required. The existing nullable `schemaErrorType` field now carries additional fixed allowlisted values. Historical v1/v2 records and the frozen R27 record remain unchanged, and current R27-style readers already copy this field without interpreting untrusted text.

`plan-extract-v6` was added as an explicit candidate using the unchanged `PlanExtractionOutputV4` schema hash. It adds rules 12–14 for the exact origin-reference matrix, unique identities, no AI-emitted USER_SUPPLEMENT binding, scalar/type/value/unit rules, `ALL|ANY` structure rules, and reciprocal SOURCE mapping. The default remains `plan-extract-v5`; `config/app.yaml`, R25/R27 prompt bytes, hashes, review packages, and historical records were not changed. Selecting v6 for any future external request changes the prompt bytes and therefore requires a newly presented exact payload and explicit approval.

## Offline verification

Before the fix, six synthetic minimal outputs all produced `field_bindings[0] / value_error`, reproducing the diagnostic collision. After the fix:

- the R28 focused suite passed `10/10`, covering all six fixed mappings, sidecar/result non-disclosure, unknown-code fallback, valid-binding acceptance, the v6 contract, frozen v6 bytes, and the v6 mapping parser;
- plan prompt, extraction, and explicit-review regression tests passed `102/102` with one pre-existing Starlette/httpx deprecation warning;
- no test was skipped or relaxed, and no validator was removed or made permissive.

The final combined regression, Ruff, formatting, and diff checks are recorded in the R28 handoff.

## Smallest future real validation recommendation

Do not start this automatically. A future candidate should answer only whether the exact fixed `LITERAL` source with a newly reviewed `plan-extract-v6` prompt reaches `SUCCEEDED`, passes the literal oracle, and remains review-only. It should permit one AI POST maximum, zero retries, zero market calls, no balance/model-list probe, no plan persistence or activation, and no trading action. Freeze the source, prompt, request body, destination, model alias, token limit, temperature, thinking mode, response format, and stop rules; recheck current official route and price immediately before dispatch.

Success requires `completed / NONE`, model match, validated usage if present, literal-oracle acceptance, one in-memory review receipt, and zero business-table writes. Any provider error, timeout, non-stop finish, JSON/schema/mapping failure, oracle mismatch, missing diagnostic, isolation failure, or uncertain receipt stops the candidate without retry. A schema failure may now identify one of R28-FB01–R28-FB06 prospectively; `other` remains the safe fallback. None of these future outcomes can retroactively identify the omitted R27 response.
