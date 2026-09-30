import { MONITOR_CONTRACT_VERSION } from "./protocol";
import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { runtimeRouter } from "./router";

document.documentElement.dataset.monitorContractVersion = String(MONITOR_CONTRACT_VERSION);
createApp(App).use(createPinia()).use(runtimeRouter).mount("#app");
