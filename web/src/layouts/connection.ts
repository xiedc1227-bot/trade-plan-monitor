import type { InjectionKey, ComputedRef } from "vue";
import type { MonitorStreamConnectionState } from "../composables/useMonitorStream";

/** An alternative application owns its stream and supplies the shell presentation. */
export const shellConnectionKey: InjectionKey<ComputedRef<MonitorStreamConnectionState>> = Symbol("shell-connection");
