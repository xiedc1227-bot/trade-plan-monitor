# Page-caption removal verification

## Scope

Remove numbered English captions above page titles in the monitor dashboard, alert center, system health, symbol detail and four backtest pages. Keep Chinese headings, descriptions, navigation and actions. Remove the obsolete `eyebrow` prop from `PageIntro.vue` and unused caption styles. Preserve backtest description styling independently of the removed caption. Update `UI02` and the component contract in both interface-design documents.

## Verification

- `npm run type-check`: passed.
- Existing unit checks for the affected pages: 7 files, 118 tests passed.
- Existing browser checks for monitoring, alert workflows and the four backtest routes: 6 tests passed, including keyboard, accessibility, 320/768/1024/1440 layouts and 200% text checks.
- `npm run build`: passed and refreshed the Python-served static distribution.
- Scoped `git diff --check`: passed. Source search found no remaining numbered English page captions or obsolete caption selectors.
- Real-browser visual inspection covered dashboard, plans, alerts, system and the backtest list. The Chinese headings remained visible and the targeted captions were absent.

## Limits

No new tests were added for this presentation-only removal. No backend, API, provider, database, dependency, commit or deployment change was made for this request. Existing unrelated work was preserved.
