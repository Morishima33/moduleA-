// 文件用途：Vite 构建配置。开发时前端跑在 5173 端口、直连本机接口；构建产物输出到 Python 包的 static 目录，由后端同源托管。
import { defineConfig } from 'vite'; // 引入 Vite 的配置函数
import react from '@vitejs/plugin-react'; // 引入 React 插件（JSX 与热更新）

// 导出配置：base 用相对路径，便于后端在任意前缀下托管
export default defineConfig({
  base: './', // 产物中的资源路径写成相对路径
  plugins: [react()], // 启用 React 支持
  server: { host: 'localhost', port: 5173, strictPort: true }, // 开发服务器固定为 localhost:5173（接口已允许此来源跨源）
  build: {
    outDir: '../src/modulea/static', // 构建产物放进后端静态目录
    emptyOutDir: false, // 保留已打开页面仍引用的历史哈希资源；入口只指向本次构建
    chunkSizeWarningLimit: 2000, // Ant Design 体积较大，放宽体积提示阈值
    sourcemap: false, // 不生成 sourcemap，减少产物体积
  },
});
