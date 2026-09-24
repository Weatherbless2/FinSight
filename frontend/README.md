# TradeAgent React 前端

这是 R-18 的 React + TypeScript + Vite 前端，后端仍使用项目根目录的 FastAPI 演示服务。

## 启动

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器默认运行在 `http://127.0.0.1:5173`，`/api` 和 `/health` 会代理到
`http://127.0.0.1:8000`。

当前项目已锁定兼容 Node.js 18 的 Vite 5 版本。没有 Node.js 时仍可使用 FastAPI 内置页面：`http://127.0.0.1:8000`。
