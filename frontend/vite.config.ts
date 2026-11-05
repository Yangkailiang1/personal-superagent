import { defineConfig } from "vite";
export default defineConfig({
  base: "/app/",
  build: {
    rolldownOptions: {
      onwarn(warning, handler) {
        // 本项目是纯客户端 SPA，不使用 RSC；保留其他构建警告。
        if (warning.code === "MODULE_LEVEL_DIRECTIVE") return;
        handler(warning);
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8002",
      "/tasks": "http://127.0.0.1:8002",
      "/accounts": "http://127.0.0.1:8002",
    },
  },
});
