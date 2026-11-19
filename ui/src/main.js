import { createApp } from "vue";
import { createPinia } from "pinia";
import naive from "naive-ui";
import App from "./App.vue";
import { router } from "./router/index.js";
import { wireUnauthorized } from "./stores/auth.js";
import "./styles/base.css";

const app = createApp(App);
app.use(createPinia());
wireUnauthorized(router);
app.use(router);
app.use(naive);
app.mount("#app");
