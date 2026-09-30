import { hasInjectionContext, inject, type InjectionKey } from "vue";

export const apiFetchKey: InjectionKey<typeof fetch> = Symbol("api-fetch");

export function resolveApiFetch(): typeof fetch {
  const provided = hasInjectionContext() ? inject(apiFetchKey, undefined) : undefined;
  return provided ?? globalThis.fetch.bind(globalThis);
}
