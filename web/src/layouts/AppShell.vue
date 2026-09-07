<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  shallowRef,
  useTemplateRef,
  watch,
} from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

import { useMonitorStream } from "../composables/useMonitorStream";
import type { MonitorStreamConnectionState } from "../composables/useMonitorStream";

defineSlots<{
  connectionBanner?(props: { state: MonitorStreamConnectionState }): unknown;
}>();

const navigationItems = [
  { to: "/", label: "监控总览" },
  { to: "/plans", label: "计划" },
  { to: "/alerts", label: "提醒" },
  { to: "/system", label: "系统" },
  { to: "/backtests", label: "回测" },
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
const { connectionState } = useMonitorStream();
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
  () => route.path,
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
      <RouterLink class="app-shell__brand" to="/">交易计划监控</RouterLink>

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
    </section>

    <main id="main-content" ref="mainContent" class="app-shell__main" tabindex="-1">
      <RouterView />
    </main>
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
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 3.5rem;
  padding-inline: 1rem;
  background: var(--color-surface-graphite);
  border-block-end: var(--border-technical);
}

.app-shell__brand,
.app-shell__navigation-link {
  color: var(--color-signal-info-cyan);
  text-decoration-thickness: 0.1em;
  text-underline-offset: 0.2em;
}

.app-shell__brand {
  font-weight: 700;
}

.app-shell__desktop-navigation {
  display: none;
}

.app-shell__navigation-list {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin: 0;
  padding: 0;
  list-style: none;
}

.app-shell__navigation-link {
  display: inline-block;
  padding: 0.65rem 0.75rem;
}

.app-shell__navigation-link.router-link-active,
.app-shell__navigation-link--current {
  font-weight: 700;
  text-decoration-thickness: 0.2em;
}

.app-shell__mobile-toggle {
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
  padding: 0.5rem 1rem;
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
  padding: 0.75rem 1rem;
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border-block-end: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.app-shell__connection-banner[data-connection-state="LIVE"] {
  border-inline-start-color: var(--color-signal-live-sea-glass);
}

.app-shell__connection-banner[data-connection-state="STALE"] {
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
  max-width: 90rem;
  margin-inline: auto;
  padding: 1rem;
}

.app-shell__main:focus-visible,
.app-shell__brand:focus-visible,
.app-shell__navigation-link:focus-visible,
.app-shell__mobile-toggle:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
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
