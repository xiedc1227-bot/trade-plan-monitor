<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  inject,
  nextTick,
  onBeforeUnmount,
  shallowRef,
  useTemplateRef,
  watch,
} from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

import { useMonitorStream } from "../composables/useMonitorStream";
import type { MonitorStreamConnectionState } from "../composables/useMonitorStream";
import { shellConnectionKey } from "./connection";

const BacktestServiceState = defineAsyncComponent(() => import("../components/backtests/BacktestServiceState.vue"));

defineSlots<{
  connectionBanner?(props: { state: MonitorStreamConnectionState }): unknown;
}>();

const navigationItems = [
  { to: "/", label: "监控总览", index: "01" },
  { to: "/plans", label: "计划", index: "02" },
  { to: "/alerts", label: "提醒", index: "03" },
  { to: "/system", label: "系统", index: "04" },
  { to: "/backtests", label: "回测", index: "05" },
] as const;

const backtestNavigationItems = [
  { to: "/backtests", label: "运行记录" },
  { to: "/backtests/new", label: "新建回测" },
  { to: "/backtests/data", label: "历史数据" },
] as const;

const route = useRoute();
const isMobileNavigationOpen = shallowRef(false);
const mainContent = useTemplateRef<HTMLElement>("mainContent");
const mobileNavigationToggle = useTemplateRef<HTMLButtonElement>("mobileNavigationToggle");
const connectionState = inject(shellConnectionKey, undefined) ?? useMonitorStream().connectionState;
const previousTitle = document.title;
const isBacktestRoute = computed(() => route.meta.section === "backtests");
const currentBacktestNavigationPath = computed(() => {
  if (route.path === "/backtests/new" || route.path === "/backtests/data") {
    return route.path;
  }
  return "/backtests";
});

let routeEffectGeneration = 0;

function focusMainContent() {
  mainContent.value?.focus();
}

function mainNavigationAriaCurrent(to: string): "location" | "page" | undefined {
  if (to === "/backtests") {
    return isBacktestRoute.value ? "location" : undefined;
  }
  return route.path === to ? "page" : undefined;
}

function toggleMobileNavigation() {
  isMobileNavigationOpen.value = !isMobileNavigationOpen.value;
}

function closeMobileNavigation(restoreFocus = false) {
  if (!isMobileNavigationOpen.value) {
    return;
  }

  isMobileNavigationOpen.value = false;
  if (restoreFocus) {
    mobileNavigationToggle.value?.focus();
  }
}

async function handleMobileNavigation() {
  closeMobileNavigation();
  await nextTick();
  mainContent.value?.focus();
}

watch(
  [() => route.path, () => route.meta.title],
  async () => {
    const activeGeneration = ++routeEffectGeneration;
    closeMobileNavigation();
    await nextTick();
    if (activeGeneration !== routeEffectGeneration) return;

    const title = route.meta.title;
    if (typeof title === "string") document.title = title;

    const heading = mainContent.value?.querySelector<HTMLElement>("h1");
    if (heading === undefined || heading === null) {
      mainContent.value?.focus();
      return;
    }
    heading.tabIndex = -1;
    heading.focus();
  },
  { flush: "post", immediate: true },
);

onBeforeUnmount(() => {
  routeEffectGeneration += 1;
  document.title = previousTitle;
});
</script>

<template>
  <div class="app-shell" @keydown.esc="closeMobileNavigation(true)">
    <a class="app-shell__skip-link" href="#main-content" @click="focusMainContent">
      跳到主要内容
    </a>

    <header class="app-shell__header">
      <RouterLink class="app-shell__brand" to="/" aria-label="交易计划监控">
        <svg class="app-shell__brand-mark" viewBox="0 0 40 40" fill="none" aria-hidden="true">
          <path d="M6 31V19M16 31V9M26 31V15M36 31V3" stroke="currentColor" stroke-width="3" />
          <path d="M2 24H39" stroke="currentColor" stroke-width="1" />
        </svg>
        <span><strong aria-hidden="true">PLAN / MONITOR</strong><span>交易计划监控</span></span>
      </RouterLink>

      <nav class="app-shell__desktop-navigation" aria-label="主要导航">
        <ul class="app-shell__navigation-list">
          <li v-for="item in navigationItems" :key="item.to">
            <RouterLink
              :class="[
                'app-shell__navigation-link',
                {
                  'app-shell__navigation-link--current':
                    item.to === '/backtests' && isBacktestRoute,
                },
              ]"
              :to="item.to"
              :aria-current="mainNavigationAriaCurrent(item.to)"
            >
              <span class="app-shell__navigation-index" aria-hidden="true">{{ item.index }}</span>
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
      </nav>

      <button
        id="mobile-navigation-toggle"
        ref="mobileNavigationToggle"
        class="app-shell__mobile-toggle"
        type="button"
        aria-controls="mobile-navigation"
        :aria-expanded="isMobileNavigationOpen"
        @click="toggleMobileNavigation"
      >
        <span aria-hidden="true">☰</span>
        <span>导航</span>
      </button>

      <nav
        id="mobile-navigation"
        class="app-shell__mobile-navigation"
        aria-label="移动端主要导航"
        :hidden="!isMobileNavigationOpen"
      >
        <ul class="app-shell__navigation-list app-shell__navigation-list--mobile">
          <li v-for="item in navigationItems" :key="item.to">
            <RouterLink
              :class="[
                'app-shell__navigation-link',
                {
                  'app-shell__navigation-link--current':
                    item.to === '/backtests' && isBacktestRoute,
                },
              ]"
              :to="item.to"
              :aria-current="mainNavigationAriaCurrent(item.to)"
              @click="handleMobileNavigation"
            >
              <span class="app-shell__navigation-index" aria-hidden="true">{{ item.index }}</span>
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
      </nav>
    </header>

    <nav v-if="isBacktestRoute" class="app-shell__backtest-navigation" aria-label="回测导航">
      <ul class="app-shell__navigation-list">
        <li v-for="item in backtestNavigationItems" :key="item.to">
          <RouterLink
            :class="[
              'app-shell__navigation-link',
              {
                'app-shell__navigation-link--current':
                  item.to === currentBacktestNavigationPath,
              },
            ]"
            :to="item.to"
            :aria-current="item.to === currentBacktestNavigationPath ? 'page' : undefined"
          >
            {{ item.label }}
          </RouterLink>
        </li>
      </ul>
    </nav>

    <section
      class="app-shell__connection-banner"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      :data-connection-state="connectionState.code"
    >
      <slot name="connectionBanner" :state="connectionState">
        <span class="app-shell__connection-marker" aria-hidden="true">
          {{ connectionState.marker }}
        </span>
        <span>{{ connectionState.label }}</span>
      </slot>
      <span class="app-shell__connection-context" aria-hidden="true">LOCAL WORKSPACE <span> / </span> UTC+08:00</span>
    </section>

    <main id="main-content" ref="mainContent" class="app-shell__main" tabindex="-1">
      <BacktestServiceState v-if="isBacktestRoute" />
      <RouterView />
    </main>
    <footer class="app-shell__footer">
      <span>PLAN / MONITOR <span class="app-shell__footer-divider">—</span> 让每一步，有据可循。</span>
      <span>交易计划 · 持续监控 · 人工决策</span>
    </footer>
  </div>
</template>

<style scoped>
:global(html) {
  color-scheme: dark;
}

:global(body) {
  margin: 0;
}

.app-shell {
  min-height: 100vh;
  color: var(--color-text-mineral);
  background: var(--color-surface-ink);
  font-family: var(--font-interface);
}

.app-shell__skip-link {
  position: fixed;
  z-index: 10;
  inset-block-start: 0.5rem;
  inset-inline-start: 0.5rem;
  padding: 0.75rem 1rem;
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: 0.125rem solid var(--color-focus-ring);
  transform: translateY(-200%);
  transition: transform 150ms ease;
}

.app-shell__skip-link:focus {
  transform: translateY(0);
}

.app-shell__header {
  position: sticky;
  top: 0;
  z-index: 6;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 5rem;
  padding-inline: max(var(--space-6), calc((100vw - 90rem) / 2));
  background: var(--color-surface-ink);
  border-block-end: var(--border-technical);
}

.app-shell__brand,
.app-shell__navigation-link {
  color: var(--color-text-muted);
  text-decoration: none;
}

.app-shell__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-mineral);
  min-width: 0;
}

.app-shell__brand-mark { flex-shrink: 0; width: clamp(1.5rem, 7vw, 2.25rem); height: clamp(1.5rem, 7vw, 2.25rem); color: var(--color-signal-watch-amber); }
.app-shell__brand > span { display: grid; gap: .125rem; min-width: 0; }
.app-shell__brand strong { font: 600 .8125rem var(--font-numeric); letter-spacing: .06em; overflow-wrap: anywhere; }
.app-shell__brand > span > span { font-size: .6875rem; color: var(--color-text-muted); letter-spacing: .16em; }
.app-shell__navigation-index { font: .625rem var(--font-numeric); color: var(--color-text-muted); }

.app-shell__desktop-navigation {
  display: none;
  min-width: 0;
}

.app-shell__navigation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin: 0;
  padding: 0;
  list-style: none;
}

.app-shell__navigation-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-control);
  transition: background-color var(--motion-fast), color var(--motion-fast);
}

.app-shell__navigation-link[aria-current],
.app-shell__navigation-link--current {
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
}

.app-shell__navigation-link[aria-current] .app-shell__navigation-index,
.app-shell__navigation-link--current .app-shell__navigation-index { color: var(--color-signal-watch-amber); }
.app-shell__navigation-link:hover { color: var(--color-text-mineral); background: var(--color-surface-graphite); }

.app-shell__mobile-toggle {
  flex-shrink: 0;
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
  min-width: 2.75rem;
  min-height: 2.75rem;
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.app-shell__mobile-navigation {
  position: absolute;
  inset-block-start: 100%;
  inset-inline: 0;
  z-index: 5;
  padding: 0.5rem 1rem 1rem;
  background: var(--color-surface-graphite);
  border-block-end: var(--border-technical);
  transition: opacity 150ms ease;
}

.app-shell__backtest-navigation {
  box-sizing: border-box;
  width: 100%;
  max-width: 100vw;
  padding: var(--space-2) max(var(--space-6), calc((100vw - 90rem) / 2));
  overflow-x: auto;
  background: var(--color-surface-graphite);
  border-block-end: var(--border-technical);
}

.app-shell__backtest-navigation .app-shell__navigation-list {
  width: max-content;
}

.app-shell__navigation-list--mobile {
  flex-direction: column;
  align-items: stretch;
}

.app-shell__connection-banner {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  padding: var(--space-2) max(var(--space-6), calc((100vw - 90rem) / 2));
  min-height: 2.75rem;
  font-size: .75rem;
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border-block-end: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.app-shell__connection-banner[data-connection-state="LIVE"] {
  border-inline-start-color: var(--color-signal-live-sea-glass);
}

.app-shell__connection-banner[data-connection-state="STALE"],
.app-shell__connection-banner[data-connection-state="MONITOR_PAUSED"] {
  border-inline-start-color: var(--color-signal-watch-amber);
}

.app-shell__connection-banner[data-connection-state="UNAVAILABLE"] {
  border-inline-start-color: var(--color-signal-watch-amber);
}

.app-shell__connection-banner[data-connection-state="DISCONNECTED"] {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.app-shell__connection-marker {
  min-width: 1em;
  font-family: var(--font-numeric);
  font-weight: 700;
  text-align: center;
}

.app-shell__main {
  max-width: 93rem;
  margin-inline: auto;
  padding: var(--space-7) var(--space-6) var(--space-8);
}

.app-shell__connection-context { margin-inline-start: auto; color: var(--color-text-muted); font: .625rem var(--font-numeric); letter-spacing: .08em; white-space: nowrap; }
.app-shell__connection-context > span { color: var(--color-signal-watch-amber); margin-inline: var(--space-3); }
.app-shell__footer { display: flex; flex-wrap: wrap; gap: var(--space-3); justify-content: space-between; max-width: 90rem; margin-inline: auto; padding: var(--space-6); border-block-start: var(--border-technical); color: var(--color-text-muted); font-size: .6875rem; letter-spacing: .04em; }
.app-shell__footer-divider { color: var(--color-signal-watch-amber); margin-inline: var(--space-2); }
.app-shell__main > :deep(*) { animation: workspace-enter var(--motion-enter) var(--ease-out) both; }
@keyframes workspace-enter { from { transform: translateY(8px); } to { transform: translateY(0); } }
@media (max-width: 39.999rem) {
  .app-shell__header { padding-inline: var(--space-4); min-height: 4.5rem; }
  .app-shell__main { padding: var(--space-6) var(--space-4) var(--space-7); }
  .app-shell__connection-banner { padding-inline: var(--space-4); }
  .app-shell__connection-context { display: none; }
  .app-shell__footer { padding: var(--space-5) var(--space-4); }
}

.app-shell__brand:focus-visible,
.app-shell__navigation-link:focus-visible,
.app-shell__mobile-toggle:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

.app-shell__main:focus-visible {
  outline: none;
}

.app-shell__main :deep(h1[tabindex="-1"]:focus-visible) {
  outline: none;
}

@media (min-width: 48rem) {
  .app-shell__desktop-navigation {
    display: block;
  }

  .app-shell__mobile-toggle,
  .app-shell__mobile-navigation {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-shell,
  .app-shell *,
  .app-shell *::before,
  .app-shell *::after {
    scroll-behavior: auto;
    transition-duration: 0.01ms;
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
  }
}
</style>
