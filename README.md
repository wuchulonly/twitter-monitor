# Twitter Monitor - 推特监控工具

一个自部署的推特（X）监控工具，可以自动追踪指定用户的推文并推送通知。支持中英双语界面。

## 核心特性

- **监控推特用户** - 定时检查指定用户的新推文，支持自定义检查间隔（最低 3 分钟）
- **多渠道通知** - 支持企业微信、Server酱、钉钉 Webhook 推送
- **媒体代理** - 后端代理推特图片/视频，前端直接查看无需翻墙
- **历史回溯** - 支持批量拉取用户的历史推文
- **多账号管理** - 支持导入多个推特账号 Cookie，自动轮换、自动处理限流
- **中英双语** - 前端界面支持中文和英文切换

## 不用梯子也能看推？原理说明

本项目使用 [twikit](https://github.com/d60/twikit) 库，它是一个逆向工程的推特客户端，模拟浏览器行为直接与推特服务端通信，**不依赖官方 API**，无需申请开发者账号。

**工作流程：**

1. 你在浏览器中登录推特，导出浏览器 Cookie（主要是 `auth_token` 和 `ct0`）
2. 通过本工具的登录页面导入 Cookie
3. 后端使用这些 Cookie 模拟浏览器请求，抓取推文数据
4. 推特的图片和视频通过后端代理转发，前端直接展示

**关于代理（梯子）：**

- 如果你的服务器**本身能访问推特**（如海外 VPS），则完全不需要任何代理，开箱即用
- 如果你的服务器**在国内**，需要配置 `TWITTER_PROXY_URL` 指向本地代理（如 Clash/Mihomo），后端通过代理去请求推特
- 但无论哪种情况，**你自己看推文时不需要梯子**——因为所有推特内容（文字、图片、视频）都由后端获取并缓存，前端只是展示后端已经拿到的数据

简单来说：**只有后端需要能访问推特，你的浏览器不需要。**

## 技术架构

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   浏览器     │────▶│  FastAPI 后端     │────▶│  Twitter/X  │
│  (前端 Vue)  │◀────│  + SQLite 数据库  │◀────│  (twikit)   │
│  无需翻墙    │     │  + 定时调度器     │     │  可选代理    │
└─────────────┘     └──────────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  通知推送     │
                    │  企业微信     │
                    │  Server酱    │
                    │  钉钉        │
                    └──────────────┘
```

**后端：** Python + FastAPI + SQLAlchemy + APScheduler + twikit

**前端：** Vue 3 + Vue Router + Vue-i18n + Axios + Vite

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+（仅开发前端时需要，已提供构建产物）

### 2. 安装

```bash
git clone https://github.com/wuchulonly/twitter-monitor.git
cd twitter-monitor

# 安装后端依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
```

### 3. 配置 `.env`

```env
DATABASE_URL=sqlite+aiosqlite:///./data/twitter_monitor.db
SECRET_KEY=your-secret-key-change-this       # 改成你自己的密钥
DEFAULT_CHECK_INTERVAL=5                      # 默认检查间隔（分钟）

# 推特代理（国内服务器需配置，海外服务器留空即可）
TWITTER_PROXY_URL=http://127.0.0.1:7890
TWITTER_PROXY_TIMEOUT=45
TWITTER_TRANSACTION_FALLBACK=true
```

### 4. 启动

```bash
# 启动后端（同时提供前端静态文件）
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

打开浏览器访问 `http://your-server-ip:8000`

### 5. 使用

1. **导入 Cookie** - 在登录页面导入你的推特浏览器 Cookie
2. **添加监控** - 填入要监控的推特用户名，设置检查间隔
3. **配置通知** - 在设置页面添加通知渠道（企业微信/Server酱/钉钉）
4. **查看推文** - 在推文页面浏览、搜索、筛选已抓取的推文

## 如何获取推特 Cookie

1. 在浏览器中登录 [x.com](https://x.com)
2. 打开开发者工具（F12）→ Application → Cookies → `https://x.com`
3. 复制 `auth_token` 和 `ct0` 的值
4. 在本工具的登录页面中以 JSON 格式导入：
   ```json
   {"auth_token": "xxx", "ct0": "xxx"}
   ```
   也支持直接粘贴 Cookie Header 字符串或 twikit 格式。

## API 接口

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/import-cookies` | POST | 导入推特 Cookie |
| `/api/auth/accounts` | GET | 获取账号列表 |
| `/api/monitors` | GET/POST | 监控列表 / 添加监控 |
| `/api/monitors/bulk` | POST | 批量添加监控 |
| `/api/monitors/{id}/backfill` | POST | 回溯历史推文 |
| `/api/tweets` | GET | 获取推文列表（支持筛选分页） |
| `/api/tweets/media` | GET | 代理推特媒体文件 |
| `/api/settings/channels` | GET/POST | 通知渠道管理 |
| `/api/settings/channels/{id}/test` | POST | 测试通知推送 |
| `/api/check-now` | POST | 立即执行一次检查 |
| `/api/health` | GET | 健康检查 |

## 前端开发

```bash
cd frontend
npm install
npm run dev    # 开发模式
npm run build  # 构建生产版本
```

## 注意事项

- Cookie 有有效期，过期后需要重新导入
- 检查间隔建议不低于 3 分钟，避免触发推特限流
- 触发限流后账号会自动暂停 15 分钟，之后自动恢复
- 支持多账号轮换，降低单账号限流风险

## License

MIT
