# 多智能体工作方案制定系统 (AgentCrew)

基于多 Agent 协作的科研工作方案制定 Web 平台，支持文献综述生成、实验方案设计等场景。系统提供用户认证、自定义 Agent 角色、人机协同审核、历史方案管理与导出等功能。

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   Web 前端 (React)                    │
│  登录 · 工作台 · 工作流监控 · Agent 管理 · 历史方案   │
└──────────────────────┬──────────────────────────────┘
                       │ REST API + WebSocket (JWT)
┌──────────────────────┴──────────────────────────────┐
│                 FastAPI 后端                          │
│  用户认证 · 工作流管理 · 人机协同 · 结果存储          │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌───────────┐ ┌─────────────┐
│ Crew 编排引擎 │ │ SQLite DB │ │  文件存储    │
│ (内存运行态)  │ │ 用户/方案  │ │ 上传/导出    │
└──────┬───────┘ └───────────┘ └─────────────┘
       │
┌──────┴──────────────────────────────────────────────┐
│  DeepSeek API  ·  工具集 (文献检索 / 文件解析 / 计算)  │
└─────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env
```

编辑 `.env`，至少配置以下项：

| 变量 | 说明 | 必填 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 是 |
| `JWT_SECRET` | JWT 签名密钥，**生产环境务必修改** | 是 |
| `ADMIN_PASSWORD` | 首次启动时创建的 admin 用户密码 | 否（默认 `admin123`） |
| `SEMANTIC_SCHOLAR_API_KEY` | 提高文献检索速率限制 | 否 |

完整配置项见 [.env.example](.env.example)。

### 2. 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 3. 启动服务

```bash
# 终端 1：启动后端（默认 http://localhost:8000）
python run.py

# 终端 2：启动前端开发服务器（默认 http://localhost:3000）
cd frontend
npm run dev
```

访问 http://localhost:3000 即可使用。前端通过 Vite 代理将 `/api` 与 `/ws` 转发至后端。

### 4. 登录

首次启动时，系统会自动创建默认管理员账号：

- **用户名**: `admin`
- **密码**: `.env` 中的 `ADMIN_PASSWORD`（默认 `admin123`）

也可在登录页注册新用户。所有业务 API 均需在登录后携带 JWT 令牌访问。

### 5. 生产部署（可选）

构建前端并由后端统一托管静态文件：

```bash
cd frontend
npm run build
python run.py
```

若存在 `frontend/dist` 目录，后端会自动挂载为根路径静态资源，此时只需启动后端服务。

## 核心功能

### 11 步实现对应

| 步骤 | 功能 | 实现位置 |
|------|------|----------|
| 1 | Agent 角色定义 | `backend/agents/roles.py` |
| 2 | 任务分解与流程 | `backend/tasks/definitions.py` |
| 3 | DeepSeek 模型连接 | `backend/llm/client.py` |
| 4 | 智能体实例构建 | `backend/crew/engine.py` → `Agent` |
| 5 | 任务对象定义 | `backend/tasks/definitions.py` → `TaskDefinition` |
| 6 | Crew 编排执行 | `backend/crew/engine.py` → `Crew` |
| 7 | 人机协同机制 | Web 审核面板 + `resume_with_feedback` |
| 8 | 运行验证调试 | WebSocket 实时日志 + 工作流页面 |
| 9 | 提示词优化 | Agent 角色 `system_prompt` 可配置 |
| 10 | 工具扩展 | `backend/tools/base.py` |
| 11 | 结果管理复用 | `backend/storage/results.py` |

### 三种场景

- **文献综述生成**: 课题规划 → 文献调研 → 方案终审
- **实验方案设计**: 课题规划 → 实验设计 → 预算编制 → 方案终审
- **完整工作方案**: 全部 5 个 Agent 协作的完整流程

工作台支持按场景勾选参与协作的 Agent 角色；取消某角色将跳过其对应任务。

### 五个内置 Agent 角色

1. **课题规划师** — 分析需求，制定研究框架
2. **文献调研专家** — 文献检索与综述（配备搜索工具）
3. **实验方案设计师** — 实验方法论设计（推理增强模型）
4. **预算资源分析师** — 资源估算与预算编制
5. **方案终审专家** — 质量评审与方案整合

除内置角色外，可在「Agent 角色」页创建、编辑、删除**用户自定义角色**（含工具绑定与推理模型开关）。

### 人机协同

在预算审批、方案终审等关键节点自动暂停，研究者可：

- 审核 Agent 输出
- 输入修改意见
- 批准继续或驳回终止

### 工作流控制

- **流式输出**: WebSocket 实时推送任务输出片段与工具调用事件
- **中止 / 继续**: 运行中可中止工作流，从中断处续写恢复
- **参考文件**: 上传 txt / md / csv / json（最大 2MB）供规划师与文献 Agent 读取
- **导出**: 完成后可导出 Markdown 或 Word（`.docx`）

### 用户与数据隔离

- JWT 认证（注册 / 登录 / 令牌校验）
- 历史方案、自定义 Agent 按用户隔离存储
- 旧版 JSON 方案文件会在首次启动时自动迁移至数据库并归属 admin 用户

## 项目结构

```
NewAPI/
├── backend/
│   ├── agents/
│   │   ├── roles.py         # 内置 Agent 角色定义
│   │   └── registry.py      # 内置 + 自定义 Agent 注册表
│   ├── auth.py              # 用户认证（注册 / 登录 / JWT）
│   ├── tasks/
│   │   ├── definitions.py   # 任务流程定义
│   │   └── filtering.py     # 按选中 Agent 过滤任务
│   ├── crew/
│   │   ├── engine.py        # Agent / Task / Crew 核心引擎
│   │   └── manager.py       # 工作流管理器
│   ├── llm/client.py        # DeepSeek API 封装
│   ├── tools/
│   │   ├── base.py          # 工具基类
│   │   ├── web_search.py    # Semantic Scholar + PubMed 文献检索
│   │   ├── code_interpreter.py  # 样本量 / 预算计算沙箱
│   │   ├── file_parser.py   # 参考文件解析
│   │   └── registry.py      # 统一工具调度
│   ├── storage/
│   │   ├── database.py      # SQLAlchemy 连接与初始化
│   │   ├── models.py        # User / WorkflowRecord / CustomAgentRecord
│   │   ├── migrate.py       # Schema 迁移与 admin 初始化
│   │   ├── results.py       # 方案存储、导出与对比
│   │   └── uploads.py       # 参考文件上传
│   ├── config.py            # 配置管理
│   └── main.py              # FastAPI 入口
├── frontend/                # React 前端（Vite + TypeScript）
├── data/
│   ├── app.db               # SQLite 数据库（默认路径）
│   ├── results/             # 旧版 JSON 方案（自动迁移后可保留作备份）
│   └── uploads/             # 用户上传的参考文件
├── tests/                   # pytest 测试
├── requirements.txt
├── run.py
└── .env.example
```

## API 概览

除 `/api/health` 与认证接口外，其余 REST API 均需在请求头携带 `Authorization: Bearer <token>`。WebSocket 连接通过查询参数 `?token=` 传递令牌。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| GET | `/api/auth/me` | 当前用户信息 |
| GET | `/api/scenarios` | 场景与任务列表 |
| GET/POST/PUT/DELETE | `/api/agents` | 自定义 Agent CRUD |
| POST | `/api/uploads` | 上传参考文件 |
| POST | `/api/workflow/start` | 启动工作流 |
| GET | `/api/workflow/{crew_id}` | 查询工作流状态 |
| POST | `/api/workflow/{crew_id}/feedback` | 提交人工审核 |
| POST | `/api/workflow/{crew_id}/suspend` | 中止工作流 |
| POST | `/api/workflow/{crew_id}/resume` | 继续工作流 |
| GET | `/api/workflow/{crew_id}/export` | 导出进行中 / 已完成方案 |
| GET | `/api/results` | 历史方案列表 |
| GET | `/api/results/{id}` | 方案详情 |
| GET | `/api/results/{id}/export` | 导出历史方案 |
| POST | `/api/results/compare` | 对比两份方案 |
| WS | `/ws/{crew_id}?token=` | 实时事件推送 |

启动后可访问 http://localhost:8000/docs 查看 Swagger 交互文档。

## 扩展指南

### 工具能力

| 工具 | 说明 | 默认使用 Agent |
|------|------|----------------|
| `web_search` | Semantic Scholar 检索，失败时回退 PubMed | 文献调研专家 |
| `file_parser` | 读取用户上传的 txt / md / csv / json 参考文件 | 课题规划师、文献调研专家 |
| `code_interpreter` | 安全沙箱内样本量与预算参数估算 | 实验方案设计师 |

可选配置 `SEMANTIC_SCHOLAR_API_KEY` 提高文献检索速率。工作台支持上传参考文件，工作流页可查看工具调用状态。

### 添加新工具

在 `backend/tools/` 下继承 `BaseTool`，并注册到 `registry.py` 的 `TOOL_REGISTRY`：

```python
class MyCustomTool(BaseTool):
    name = "my_tool"
    description = "工具描述"
    async def run(self, **kwargs) -> str:
        return "结果"
```

同时在 `backend/agents/registry.py` 的 `VALID_TOOLS` 与 `main.py` 的工具标签映射中注册新工具 ID。

### 添加新场景

1. 在 `ScenarioType` 枚举中添加场景（`backend/agents/roles.py`）
2. 在 `SCENARIO_AGENTS` 中配置参与的 Agent
3. 在 `TASK_FLOWS` 中定义任务流程（`backend/tasks/definitions.py`）

### 调整提示词

- **内置角色**: 修改 `backend/agents/roles.py` 中各 Agent 的 `background` 和 `goal` 字段
- **自定义角色**: 通过 Web 界面或 `/api/agents` 接口管理

## 测试

```bash
pytest
```

测试覆盖 Agent 注册表、工具模块、文件上传、Crew 引擎等核心逻辑。测试使用独立临时数据库，不影响 `data/app.db`。

## 技术栈

- **后端**: Python 3.11+, FastAPI, SQLAlchemy, httpx, bcrypt, PyJWT
- **前端**: React 18, TypeScript, Vite
- **数据库**: SQLite（默认，可通过 `DATABASE_URL` 替换）
- **大模型**: DeepSeek API（`deepseek-chat` / `deepseek-reasoner`）
- **通信**: REST API + WebSocket 实时推送

## 注意事项

- **运行中工作流**保存在内存中，服务重启后将丢失进行中的任务；已完成方案持久化在 SQLite。
- 生产部署前请修改 `JWT_SECRET` 与 `ADMIN_PASSWORD`，并限制 CORS 允许的域名。
- `data/` 目录包含数据库与上传文件，建议纳入备份策略。
