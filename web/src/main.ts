import { createApp } from "vue";
import type { App, Component } from "vue";
import { createPinia } from "pinia";

import RootApp from "./App.vue";
import { router } from "./router";

export function createMonitorApp(
  rootComponent: Component = RootApp,
  rootProps?: Record<string, unknown>,
): App<Element> {
  const app = createApp(rootComponent, rootProps);

  if (rootComponent === RootApp) {
    app.use(createPinia());
    app.use(router);
  }

  return app;
}

const mountTarget = document.querySelector("#app");

if (mountTarget !== null) {
  createMonitorApp().mount(mountTarget);
}
