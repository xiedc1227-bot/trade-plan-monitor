<script setup lang="ts">
import { nextTick, shallowRef, useTemplateRef } from "vue";
import { RouterLink, RouterView } from "vue-router";

defineSlots<{
  connectionBanner?(): unknown;
}>();

const navigationItems = [
  { to: "/", label: "监控总览" },
  { to: "/plans", label: "计划" },
  { to: "/alerts", label: "提醒" },
  { to: "/system", label: "系统" },
] as const;

const isMobileNavigationOpen = shallowRef(false);
const mainContent = useTemplateRef<HTMLElement>("mainContent");
const mobileNavigationToggle = useTemplateRef<HTMLButtonElement>("mobileNavigationToggle");

function focusMainContent() {
  mainContent.value?.focus();
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
            <RouterLink class="app-shell__navigation-link" :to="item.to">
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
              class="app-shell__navigation-link"
              :to="item.to"
              @click="handleMobileNavigation"
            >
              {{ item.label }}
            </RouterLink>
          </li>
        </ul>
      </nav>
    </header>

    <section
      v-if="$slots.connectionBanner"
      class="app-shell__connection-banner"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <slot name="connectionBanner" />
    </section>

    <main id="main-content" ref="mainContent" class="app-shell__main" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
:global(html) {
  color-scheme: dark light;
}

:global(body) {
  margin: 0;
}

.app-shell {
  min-height: 100vh;
  color: CanvasText;
  background: Canvas;
  font-family: system-ui, sans-serif;
}

.app-shell__skip-link {
  position: fixed;
  z-index: 10;
  inset-block-start: 0.5rem;
  inset-inline-start: 0.5rem;
  padding: 0.75rem 1rem;
  color: CanvasText;
  background: Canvas;
  border: 0.125rem solid Highlight;
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
  border-block-end: 0.0625rem solid GrayText;
}

.app-shell__brand,
.app-shell__navigation-link {
  color: LinkText;
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

.app-shell__navigation-link.router-link-active {
  font-weight: 700;
  text-decoration-thickness: 0.2em;
}

.app-shell__mobile-toggle {
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
  min-width: 2.75rem;
  min-height: 2.75rem;
  color: ButtonText;
  background: ButtonFace;
  border: 0.0625rem solid ButtonBorder;
}

.app-shell__mobile-navigation {
  position: absolute;
  inset-block-start: 100%;
  inset-inline: 0;
  z-index: 5;
  padding: 0.5rem 1rem 1rem;
  background: Canvas;
  border-block-end: 0.0625rem solid GrayText;
  transition: opacity 150ms ease;
}

.app-shell__navigation-list--mobile {
  flex-direction: column;
  align-items: stretch;
}

.app-shell__connection-banner {
  padding: 0.75rem 1rem;
  border-block-end: 0.0625rem solid GrayText;
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
  outline: 0.1875rem solid Highlight;
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
