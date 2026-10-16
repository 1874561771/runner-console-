# Runner Console 前端（零构建骨架）

纯静态 ES Modules，浏览器原生加载，无 npm / 无打包。

## 预览

`file://` 下 ES Module 受 CORS 限制，需起本地 HTTP 服务：

```
python -m http.server 8000
# 浏览器打开 http://localhost:8000/frontend/
```

## Mock 模式

后端未就绪时开发用：

```
http://localhost:8000/frontend/?mock=1
```

或在控制台执行 `localStorage.setItem("rc_mock","1")` 后刷新。

## 结构

```
frontend/
├── index.html            壳：顶栏 + 左导航 + #view + 登录浮层
├── css/
│   └── design-tokens.css CSS 变量全套 + 基础组件类
└── js/
    ├── main.js           装配入口（/api/me → router）
    ├── api.js            apiFetch（401→AuthError+登出事件）+ mock 拦截 + SSE
    ├── mock-data.js      mock 内存假数据（loops/jobs/runs/cases/envs/users/audit/stats）
    ├── store.js          极简状态 + 事件总线（on/emit/off）
    ├── router.js         hash 路由（#/console 默认 /tasks /dashboard /resources /admin）
    └── views/            console.js / tasks.js / dashboard.js / resources.js / admin.js（T10-T12 实现）
```

Chart.js（T12 数据看板用）允许 CDN 引入，当前未引入。
