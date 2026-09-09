# Spec: index-identity

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-index-identity.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Provide the only allowed Phase-1 mapping from a validated A-share stock code to its board reference index. The mapping is deterministic, closed, versioned, free of provider calls, and contains no trading judgment.

## Tech Stack and Commands

- Python 3.14, frozen strict Pydantic values, `StrEnum`, and pytest.
- No database, clock, network, AI, browser, or provider dependency.

```powershell
python -m pytest tests/unit/test_market_index_identity.py -q
python -m ruff check src/trade_plan_monitor/market_index tests/unit/test_market_index_identity.py
```

## Project Structure

```text
src/trade_plan_monitor/market_index/
├── __init__.py
└── identity.py
tests/unit/
└── test_market_index_identity.py
```

## Public Contract

`MAPPING_VERSION` is the literal `board-index-map-v1`. `ReferenceMarketSelection` is the literal `AUTO_BOARD`.

```python
class Board(StrEnum):
    SSE_MAIN = "SSE_MAIN"
    SZSE_MAIN = "SZSE_MAIN"
    CHINEXT = "CHINEXT"
    STAR_MARKET = "STAR_MARKET"
    BSE = "BSE"

class MarketIndexCode(StrEnum):
    SSE_COMPOSITE = "000001.SH"
    SHENZHEN_COMPONENT = "399001.SZ"
    CHINEXT = "399006.SZ"
    STAR_50 = "000688.SH"
    BSE_50 = "899050.BJ"

class ReferenceMarketBinding(BaseModel):
    selection: Literal["AUTO_BOARD"]
    mapping_version: Literal["board-index-map-v1"]
    index_code: MarketIndexCode

def resolve_board_reference(symbol: str) -> ResolvedMarketIndexIdentity: ...
def validate_reference_market_binding(symbol: str, binding: ReferenceMarketBinding) -> None: ...
```

`ResolvedMarketIndexIdentity` additionally exposes the derived `board` and immutable Chinese `display_name` for projection. Only `selection`, `mapping_version`, and `index_code` are stored in a plan. Display text and board are derived facts and do not create a second mapping source.

## Fixed Mapping

| Validated stock rule | `board` | `index_code` | `display_name` |
|---|---|---|---|
| `.SH` and prefix is neither `688` nor `689` | `SSE_MAIN` | `000001.SH` | `上证指数` |
| `.SZ` and prefix is neither `300` nor `301` | `SZSE_MAIN` | `399001.SZ` | `深证成指` |
| `.SZ` and prefix is `300` or `301` | `CHINEXT` | `399006.SZ` | `创业板指` |
| `.SH` and prefix is `688` or `689` | `STAR_MARKET` | `000688.SH` | `科创50` |
| `.BJ` | `BSE` | `899050.BJ` | `北证50` |

This mapping preserves plan and stored-data identity; it does not imply current live-provider support. BSE 50 is `DEFERRED` while no BSE stocks are traded. Live certification and production provider acquisition make no request for `899050.BJ`; bringing BSE stocks into scope requires a separate specification and certification change.

The input must first match the existing canonical stock pattern `^[0-9]{6}\.(SH|SZ|BJ)$`. Classification uses only the code and suffix. Company names, AI output, index membership, remote classification, and fallback indices are forbidden. Invalid or unclassifiable input raises a stable validation error before any provider call.

## Plan and Hash Boundary

- A Schema v2 draft receives a backend-derived binding after the stock symbol validates.
- Import, save, activation, backtest submission, and replay recompute the binding and reject any mismatch.
- The canonical plan JSON contains the three binding fields exactly, so existing `plan_sha256` includes `schema_version`, `selection`, `mapping_version`, and `index_code` without a second hash algorithm.
- Schema v1 documents never gain a binding and keep byte-identical canonical JSON and hashes.
- A future mapping change requires a new mapping version and a new immutable plan version; `board-index-map-v1` is never edited in place.

## Testing Strategy

- Table-drive all five exact mapping branches, including `688`/`689` and `300`/`301` equality boundaries.
- Reject malformed lengths, suffixes, lowercase exchanges, whitespace, index codes passed as stock codes, and arbitrary strings.
- Prove each valid symbol resolves once, the returned value is immutable, and no fallback exists.
- Prove a matching binding validates and every changed mapping field or stock symbol fails.
- Prove Schema v1 hash goldens remain unchanged and a Schema v2 binding changes the plan hash.

## Boundaries

- Always: validate the stock code before classification and retain `board-index-map-v1` in evidence.
- Ask first: add a board, change a binding, add user-selected benchmarks, or create a new mapping version.
- Never: infer from names, constituents, providers, AI, or industry classifications; never fall back to another index.

## Success Criteria

- Every canonical `.SH`, `.SZ`, or `.BJ` stock code maps to exactly one approved board index.
- Invalid input fails before I/O and cannot silently select a benchmark.
- Stored bindings are recomputable, immutable, and hash-sensitive.
- No industry index or universal market conclusion exists in this module.

## Review Status

The bilingual board-index proposal and ADR 0003 were approved on `2026-09-02`. The current user request authorizes this specification, implementation, and offline verification, but not commit, push, dependency installation, deployment, or real provider network access.
