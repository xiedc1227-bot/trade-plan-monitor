import { createApp } from "vue";
import type { App, Component } from "vue";

export function createMonitorApp(
  rootComponent: Component,
  rootProps?: Record<string, unknown>,
): App<Element> {
  return createApp(rootComponent, rootProps);
}
