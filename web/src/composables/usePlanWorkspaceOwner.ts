import { computed, readonly, shallowRef } from "vue";

export interface WorkspaceOperation {
  readonly kind: "LOAD" | "ACTION";
  readonly generation: number;
  readonly sequence: number;
}
export interface WorkspaceLoad extends WorkspaceOperation {
  readonly kind: "LOAD";
  readonly signal: AbortSignal;
}

/** UI ownership only: invalidating an observation does not undo a sent POST. */
export function usePlanWorkspaceOwner() {
  const generation = shallowRef(0);
  const loading = shallowRef(false);
  const mutating = shallowRef(false);
  let disposed = false, loadSequence = 0, actionSequence = 0;
  let loadController: AbortController | null = null;

  function invalidate() {
    generation.value++;
    loadController?.abort(); loadController = null;
    loading.value = false;
  }
  function beginLoad(): WorkspaceLoad | null {
    if (disposed) return null;
    invalidate();
    const controller = new AbortController(); loadController = controller;
    loading.value = true;
    return Object.freeze({ kind: "LOAD", generation: generation.value,
      sequence: ++loadSequence, signal: controller.signal });
  }
  function beginAction(): WorkspaceOperation | null {
    if (disposed || loading.value || mutating.value) return null;
    mutating.value = true;
    return Object.freeze({ kind: "ACTION", generation: generation.value, sequence: ++actionSequence });
  }
  function current(operation: WorkspaceOperation): boolean {
    return !disposed && operation.generation === generation.value &&
      (operation.kind === "LOAD" ? operation.sequence === loadSequence &&
        loadController !== null && !loadController.signal.aborted : operation.sequence === actionSequence);
  }
  function finish(operation: WorkspaceOperation) {
    if (operation.kind === "ACTION") {
      if (operation.sequence === actionSequence) mutating.value = false;
    } else if (current(operation)) { loading.value = false; loadController = null; }
  }
  function dispose() { disposed = true; invalidate(); }
  return { generation: readonly(generation), busy: computed(() => loading.value || mutating.value),
    beginLoad, beginAction, current, finish, invalidate, dispose };
}
