import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时：前端跑在 5173，/api 代理到本地的 python -m app.web
// 构建后：产物在 web/dist，由 app/web.py 直接托管
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": "/src" },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
});
