# Interface design contract

## Scope

`UI01`: Refine the installed monitor-contract `2` interface and the shared shell, market components, and controls used by the compatibility interface. Preserve all routes, REST/WebSocket fields, authority, deadlines, and user-command boundaries. This is a presentation change; no provider request, production data mutation, deployment, or new dependency is required.

## Direction and references

Use an original precision-workbench identity: warm ink surfaces, mineral text, amber actions, restrained sea-glass and vermilion status colors, a custom threshold mark, tabular figures, and numbered navigation. The dashboard prioritizes monitoring facts over decoration.

- [Terminal Industries / Awwwards](https://www.awwwards.com/sites/terminal-industries): reference for a coherent technical identity and deliberate hierarchy; do not copy its layout or assets.
- [Google Fonts](https://fonts.google.com/) and [Webby Best User Interface](https://winners.webbyawards.com/winners/websites-and-mobile-sites/features-design/best-user-interface): reference for legible type, structured controls, and scan order.
- [FWA](https://thefwa.com/): creative-quality reference. Award status is a benchmark, not a certification of this implementation. Live visual access to Awwwards/FWA was limited; no claim of an exhaustive reference audit.

## Component boundaries

| Component | Responsibility | Contract |
|---|---|---|
| `AppShell.vue` | Brand, navigation, connection banner, focus routing | Existing route/connection state and slot |
| `PageIntro.vue` | Consistent page hierarchy | `title`, `eyebrow`, `description`; action slot |
| `DashboardView.vue` in `runtime-status` | Compose current facts, market, status, and active plans | Existing runtime context; no policy calculation |
| `OverviewStatus.vue` | Separate transport certainty from monitoring readiness | Existing readonly status/live props |
| `PlanDraftingView.vue`, `PlanWorkbench.vue` | Compose the AI review workspace independently of configuration loading | `runtimeLoading` controls configuration-dependent actions; preserve early source input |
| `AIProviderSelector.vue`, `SourceTextEditor.vue` | Show local configuration progress and separate editing from submission eligibility | `loading`, `submitDisabled`; existing selection/input events |
| `MarketIndexDataStrip.vue` and market cards | Select and present authoritative market facts | Existing props/events unchanged |
| `tokens.css`, `runtime.css` | Shared typography, colors, controls, motion, and responsive layouts | Semantic tokens; no remote resources |

## Acceptance criteria

- `UI02` Typography and whitespace: one clear page title, readable supporting text, tabular numbers, and a 4px spacing rhythm; primary facts remain prominent.
- `UI03` Hierarchy and color: actions, facts, diagnostics, and unavailable/cached states remain distinct. Normal text contrast is at least 4.5:1; large text at least 3:1. Status always has text.
- `UI04` Motion and interaction: restrained entrance/hover/press feedback, visible keyboard focus, working mobile navigation and Escape behavior. `prefers-reduced-motion` disables nonessential movement. No scroll hijacking or decorative live-data animation.
- `UI05` Responsive: inspect 320px, 768px, 1024px, and 1440px. No page-level horizontal overflow; dense tables may scroll locally. Mobile controls remain usable with 44px targets. In the wide workspace, align the monitoring panel's top with the actual index surface, below its heading; preserve status-first stacking on narrow layouts. Place trend error text and retry to the right of the full-day turnover estimate when space permits, stacking below on small screens; reserve no action column when the action slot is absent.
- `UI06` Originality: custom brand mark, numbered navigation, and purposeful dashboard composition; no stock hero, fabricated metrics, copied imagery, or generic gradient/card grid.
- `UI07` Verification: type check, unit suite, production build, relevant browser journeys and axe checks; visually review dashboard, plans, alerts, system, and backtests. Record actual results and limitations in paired verification reports.
- `UI08` Plan startup: render the AI review heading, source editor, and review area before the configuration response. Allow early source input, disable submission until a configured enabled provider is available, and preserve the input when configuration arrives or fails. Apply the loaded provider's input limit before submission; configuration errors remain visible and cannot trigger extraction automatically.

## Iteration rule

Review all eight requested dimensions after the first working slice. Correct concrete issues found by screenshots or tests and repeat affected checks. Completion means no obvious actionable issue remains in the inspected states; subjective award recognition cannot be guaranteed.
