import type { InjectionKey } from "vue";

export const initialResultSettledKey: InjectionKey<(path: string) => void> = Symbol("initial-result-settled");

/** Owns only the first monitor start, never an already running monitor. */
export function createInitialResultStartup(start: () => void) {
  let mounted = false;
  let closed = false;
  let started = false;
  let initialPath: string | null = null;
  let settledPath: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  function clear(): void { clearTimeout(timer); timer = undefined; }
  function release(): void {
    if (!mounted || closed || started) return;
    started = true; clear(); start();
  }
  return {
    mount(): void {
      if (closed || mounted) return;
      mounted = true;
      timer = setTimeout(release, 5000);
    },
    route(path: string, result: boolean): void {
      if (closed || started) return;
      if (!result || (initialPath !== null && initialPath !== path)) { release(); return; }
      initialPath = path;
      if (settledPath === path) release();
    },
    settled(path: string): void {
      if (closed || started) return;
      settledPath = path;
      if (path === initialPath) release();
    },
    dispose(): void { closed = true; clear(); },
  };
}
