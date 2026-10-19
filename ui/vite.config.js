import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// base=/v2/ ：构建产物由 FastAPI 挂载在 /v2/（迁移期旧前端仍在 /）
// 开发：npm run dev（5173），/api 反代到本机 8765 后端
export default defineConfig({
  plugins: [vue()],
  base: "/v2/",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/runs": "http://127.0.0.1:8765",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
