````sql
# AI智能体测试平台——技术开发架构方案

## 最终版 V5.0（完整定稿版）

> 基于PRD V5.0完整定稿版生成
> 本文档为开发唯一架构真理源，完整独立，不引用任何历史版本
> 本文档为架构设计文档，供AI编码工具作为开发依据

---

## 文档信息

| 项目 | 内容 |
|------|------|
| **文档版本** | V5.0（最终定稿） |
| **文档状态** | 已定稿 |
| **技术栈** | Python 3.12（已确认）+ Django 5.0 + LangChain 0.3 + LangGraph 0.2 + LangSmith + Vue3(JavaScript) + 纯CSS + Celery 5.4 + Redis 7 + PostgreSQL 16 |
| **部署方式** | 本地Python 3.12虚拟环境开发；腾讯云独立Docker联调环境；公司服务器部署方式上线前确认 |
| **对应PRD** | AI智能体测试平台PRD V5.0 |
| **设计原则** | 模块化、插件化、可扩展 |

**🟧【V5.1 已人工验收】以下带“🟧”的内容为本次新增或调整，现已纳入正式技术基线。**


## 目录

1. [技术选型总览](#1-技术选型总览)
2. [系统架构设计](#2-系统架构设计)
3. [项目目录结构](#3-项目目录结构)
4. [数据库设计](#4-数据库设计)
5. [LangGraph智能体设计](#5-langgraph智能体设计)
6. [多模型管理设计](#6-多模型管理设计)
7. [提示词管理设计](#7-提示词管理设计)
8. [知识库与检索设计](#8-知识库与检索设计)
9. [需求分析与用例生成设计](#9-需求分析与用例生成设计)
10. [业务联调设计](#10-业务联调设计)
11. [Skills技能系统设计](#11-skills技能系统设计)
12. [测试执行引擎设计](#12-测试执行引擎设计)
13. [代码自动生成器设计](#13-代码自动生成器设计)
14. [测试环境管理设计](#14-测试环境管理设计)
15. [Git集成设计](#15-git集成设计)
16. [通知中心设计](#16-通知中心设计)
17. [主动建议引擎设计](#17-主动建议引擎设计)
18. [测试资产与ROI设计](#18-测试资产与roi设计)
19. [Celery异步任务设计](#19-celery异步任务设计)
20. [前端架构设计](#20-前端架构设计)
21. [API接口设计](#21-api接口设计)
22. [服务器部署方案](#22-服务器部署方案)
23. [扩展性设计](#23-扩展性设计)
24. [开发路线图](#24-开发路线图)


## 1. 技术选型总览

### 1.1 技术栈清单

| 层级 | 技术 | 版本 | 用途 | 选型理由 |
|------|------|------|------|---------|
| 前端框架 | Vue3 | 3.4+ | SPA应用 | 组合式API，生态成熟 |
| 前端语言 | JavaScript | ES6+ | 前端开发 | 团队熟悉，降低门槛 |
| 样式方案 | 纯CSS（CSS变量） | — | 页面样式 | 无额外依赖，CSS变量支持主题定制 |
| 构建工具 | Vite | 5.0+ | 前端构建 | 快速冷启动 |
| UI组件库 | Element Plus | 2.7+ | UI组件 | 企业级组件丰富 |
| 状态管理 | Pinia | 2.1+ | 前端状态 | Vue3官方推荐 |
| HTTP客户端 | Axios | 1.7+ | API调用 | 拦截器强大 |
| Markdown渲染 | markdown-it | 14+ | 报告展示 | 轻量快速 |
| 图表库 | ECharts | 5.5+ | 数据可视化 | 功能全面 |
| 后端框架 | Django | 5.0+ | 业务逻辑 | ORM/Admin/认证成熟 |
| API框架 | DRF | 3.15+ | REST API | Django标准搭配 |
| AI编排 | LangChain | 0.3+ | AI能力封装 | 模型/工具/检索统一接口 |
| 图编排 | LangGraph | 0.2+ | 智能体状态机 | 复杂流程编排 |
| AI监控 | LangSmith | - | 调试追踪 | 智能体可观测性 |
| 异步任务 | Celery | 5.4+ | 长任务处理 | 测试执行/定时任务 |
| 定时调度 | Celery Beat | 5.4+ | 定时任务 | 定时回归/健康检查 |
| 数据库 | PostgreSQL | 16 | 业务数据 | 稳定可靠 |
| 向量扩展 | pgvector | 0.7+ | 向量存储 | 免去独立向量库 |
| 缓存/队列 | Redis | 7+ | 缓存/队列 | Celery Broker |
| WSGI服务器 | Gunicorn | 22+ | 生产服务 | 稳定高效 |
| 🟩 RAG数据框架【RAG二阶段】 | 🟩 LlamaIndex（由T133兼容性验证后锁定版本） | 🟩 按验证结果固定版本 | 🟩 文档节点化、索引与检索适配 | 🟩 不接管Django业务模型、权限与主流程编排 |
| 🟧 工具协议【V5.1】 | 🟧 MCP（以实施时确认的稳定规范为准） | 🟧 待锁定 | 🟧 工具、资源、提示词的标准接入 | 🟧 统一外部能力边界 |
| 🟧 人工介入【V5.1】 | 🟧 LangGraph HITL | 🟧 随已锁定LangGraph版本演进 | 🟧 中断、审批、恢复、超时 | 🟧 复用现有状态图，避免第二套状态机 |
| 🟧 多智能体适配【V5.1】 | 🟧 CrewAI（可选） | 🟧 第三期评估后锁定 | 🟧 专业智能体协作试点 | 🟧 通过适配器被LangGraph调用 |
| 🟧 兼容性评估【V5.1】 | 🟧 AutoGen / Microsoft Agent Framework | 🟧 不进入当前生产依赖 | 🟧 迁移与互操作研究 | 🟧 避免采用已进入维护模式的框架作为新核心 |

### 1.2 测试框架兼容清单

| 测试类型 | 框架 | 说明 |
|---------|------|------|
| 接口测试 | requests + pytest | 含业务联调 |
| UI测试(Web) | Playwright + pytest + POM | 默认 |
| UI测试(兼容) | Selenium | 兼容老项目 |
| APP测试 | Appium + pytest + adb | Android/iOS/小程序 |
| 性能测试(默认) | Locust | Python代码生成 |
| 性能测试(兼容) | JMeter | JMX复用/生成 |
| 数据驱动 | dataclass/JSON/YAML/Excel/CSV | 多格式 |

### 1.3 在线文档支持

| 平台 | 接入方式 |
|------|---------|
| 腾讯文档 | 链接 + OAuth |
| 飞书文档 | 链接 + API Token |
| 语雀 | 链接 + API |
| Notion | 链接 + API Token |
| Confluence | 链接 + API |
| Swagger UI | 链接直接解析 |
| YApi/Apifox | 链接直接解析 |
| 通用网页 | URL抓取 |


## 2. 系统架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端层（Vue3 + JavaScript + 纯CSS）       │
│  页面 │ 组件 │ 状态管理(Pinia) │ API封装(Axios) │ SSE通信       │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS / REST API / SSE
┌──────────────────────────────▼──────────────────────────────────┐
│                      API层（Django + DRF）                      │
│  认证 │ 权限 │ 路由 │ 序列化 │ 验证 │ 分页                     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    业务逻辑层（Django Apps）                     │
│  users │ projects │ agents │ requirement │ case_gen │ tests    │
│  knowledge │ skills │ environments │ notifications │ git      │
│  proactive │ test_assets │ roi │ reports │ configs             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                  AI编排层（LangChain + LangGraph）               │
│  感知 → 理解 → 检索 → 规划 → 决策 → 执行 → 反思 → 学习 → 报告  │
└──────┬───────────────────┬───────────────────┬──────────────────┘
       │                   │                   │
┌──────▼──────┐  ┌─────────▼─────────┐  ┌──────▼──────────────┐
│  工具层      │  │  异步任务层        │  │  框架适配层          │
│  HTTP       │  │  Celery Worker    │  │  接口: pytest        │
│  Playwright │  │  Celery Beat      │  │  UI: Playwright     │
│  Appium     │  │  测试执行         │  │  APP: Appium        │
│  JMeter     │  │  知识处理         │  │  性能: Locust/JMeter│
│  Locust     │  │  通知发送         │  │  报告: 自然语言报告  │
│  adb        │  │  Git分析          │  │                     │
│  截图识别   │  │  主动建议         │  │                     │
│  在线文档   │  │  定时任务         │  │                     │
└──────┬──────┘  └─────────┬─────────┘  └──────────────────────┘
       │                   │
┌──────▼───────────────────▼──────────────────────────────────────┐
│                        数据层                                   │
│  PostgreSQL 16 + pgvector │ Redis 7 │ 文件存储                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 服务进程拓扑

> 本地开发不依赖Docker，使用SQLite与Celery eager模式；腾讯云联调环境使用独立Compose项目、网络和数据卷，不影响既有`aits`系统。

```
┌─────────────────────────────────────────────────────────────────┐
│                       服务器内部服务网络                          │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ frontend │  │ backend  │  │  redis   │  │ postgres │       │
│  │ Vue3+JS  │  │ Django   │  │  :6379   │  │ :5432    │       │
│  │ +纯CSS   │  │ :8000    │  │          │  │ +pgvector│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────────┐  │
│  │celery    │  │celery    │  │     可选容器                  │  │
│  │worker    │  │beat      │  │  ┌─────────────────────────┐ │  │
│  └──────────┘  └──────────┘  │  │        jmeter           │ │  │
│                               │  └─────────────────────────┘ │  │
│                               │  ┌─────────────────────────┐ │  │
│                               │  │      nginx/caddy        │ │  │
│                               │  └─────────────────────────┘ │  │
│                               └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 核心请求流转

```
用户输入"帮我分析这个需求文档" + 粘贴在线文档链接
    ↓
前端(Vue3) → POST /api/chat/message
    ↓
Django API → 创建对话记录 → 异步提交Celery任务
    ↓
Celery Worker → 调用LangGraph
    ↓
LangGraph图执行：
  感知 → 理解(意图识别) → 在线文档获取 → 文档解析
  → 需求深度分析 → 联合功能识别 → 测试点分析
  → 用例生成(5轮) → 用例评审(5轮) → 自动化筛选
  → 覆盖度报告 → 通知推送
    ↓
Django保存结果 → SSE推送前端
    ↓
前端展示分析结果和用例列表
```


### 2.4 🟧 【V5.1 架构边界基线】新增框架职责边界

🟧 系统必须保持一个主编排器：LangGraph负责会话状态、条件路由、重试、Celery衔接和最终执行状态，其他框架不得绕过LangGraph直接改变任务生命周期。

| 🟧 层级 | 🟧 唯一职责 | 🟧 禁止事项 |
|---|---|---|
| 🟧 LangGraph主编排层 | 🟧 确定性流程、状态持久化、HITL中断与恢复 | 🟧 不得把主状态所有权交给CrewAI或AutoGen |
| 🟩 LlamaIndex数据适配层【阶段24实施】 | 🟩 文档连接器、节点化、索引、检索器适配 | 🟩 不得替代Django ORM、PostgreSQL业务表或权限体系 |
| 🟧 MCP能力网关 | 🟧 发现并调用Tools/Resources/Prompts，执行能力协商 | 🟧 不得默认信任服务器，不得自动获得完整对话或跨项目数据 |
| 🟧 HITL治理层 | 🟧 风险确认、审批、暂停、恢复、超时和驳回 | 🟧 不得与开发过程的人工任务确认门禁混为一谈 |
| 🟧 AgentRuntimeAdapter | 🟧 隔离CrewAI等可选运行时的输入、输出、事件和错误 | 🟧 业务Service不得直接导入可选多智能体框架 |

🟧 多智能体默认不启用。只有单智能体无法合理完成、职责可清晰拆分且额外模型成本得到用户确认时，才允许进入多智能体路径。相同任务不得同时由LangGraph、CrewAI和AutoGen重复编排。

🟧 MCP调用链固定为：意图与项目上下文 → T006权限校验 → Server信任与能力校验 → 参数验证 → 必要时HITL确认 → 调用 → 结果脱敏与审计 → 返回LangGraph。高风险写操作必须默认拒绝并等待人工确认。

## 3. 项目目录结构

```
ai-agent-test-platform/
│
├── .env.example                        # 环境变量模板
├── .gitignore
├── README.md
│
├── frontend/                           # Vue3前端（JavaScript + 纯CSS）
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   │
│   └── src/
│       ├── main.js                     # 入口
│       ├── App.vue
│       │
│       ├── router/
│       │   └── index.js                # 路由配置
│       │
│       ├── styles/                     # 纯CSS样式
│       │   ├── index.css               # 全局入口
│       │   ├── variables.css           # CSS变量
│       │   ├── theme.css               # 主题
│       │   ├── chat.css                # 对话样式
│       │   └── components.css          # 组件样式
│       │
│       ├── stores/                     # Pinia状态
│       │   ├── user.js                 # 用户
│       │   ├── chat.js                 # 对话
│       │   ├── agent.js                # 智能体
│       │   ├── knowledge.js            # 知识库
│       │   ├── test.js                 # 测试
│       │   ├── environment.js          # 环境
│       │   ├── notification.js         # 通知
│       │   ├── requirement.js          # 需求分析
│       │   ├── caseGen.js              # 用例生成
│       │   └── roi.js                  # ROI
│       │
│       ├── api/                        # API封装
│       │   ├── request.js              # Axios实例
│       │   ├── auth.js
│       │   ├── chat.js
│       │   ├── agent.js
│       │   ├── knowledge.js
│       │   ├── skills.js
│       │   ├── test.js
│       │   ├── report.js
│       │   ├── model.js
│       │   ├── prompt.js
│       │   ├── environment.js
│       │   ├── notification.js
│       │   ├── git.js
│       │   ├── requirement.js
│       │   ├── caseGen.js
│       │   ├── coverage.js
│       │   └── roi.js
│       │
│       ├── views/                      # 页面（20个）
│       │   ├── LoginView.vue
│       │   ├── ChatView.vue            # 对话主界面
│       │   ├── DashboardView.vue
│       │   ├── AgentManageView.vue
│       │   ├── KnowledgeBaseView.vue
│       │   ├── SkillsView.vue
│       │   ├── TestCaseView.vue
│       │   ├── TestRunView.vue
│       │   ├── ReportView.vue
│       │   ├── ModelConfigView.vue
│       │   ├── PromptConfigView.vue
│       │   ├── EnvironmentView.vue
│       │   ├── GitIntegrationView.vue
│       │   ├── NotificationCenter.vue
│       │   ├── RequirementAnalysisView.vue
│       │   ├── CaseGenerationView.vue
│       │   ├── CoverageReportView.vue
│       │   ├── ROIView.vue
│       │   ├── ProjectManageView.vue
│       │   └── SystemSettingsView.vue
│       │
│       ├── components/                 # 组件
│       │   ├── chat/                   # 对话组件
│       │   ├── requirement/            # 需求分析组件
│       │   ├── case/                   # 用例组件
│       │   ├── test/                   # 测试组件
│       │   ├── environment/            # 环境组件
│       │   ├── notification/           # 通知组件
│       │   └── common/                 # 通用组件
│       │
│       ├── composables/                # 组合式函数
│       │   ├── useChat.js
│       │   ├── useSSE.js
│       │   ├── useTestRun.js
│       │   ├── useEnvironment.js
│       │   ├── useNotification.js
│       │   ├── useRequirement.js
│       │   └── useCaseGen.js
│       │
│       └── utils/
│           ├── markdown.js
│           ├── format.js
│           ├── storage.js
│           └── constants.js
│
├── backend/                            # Django后端
│   ├── requirements.txt
│   ├── manage.py
│   │
│   ├── config/                         # 项目配置
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── settings/
│   │       ├── base.py
│   │       ├── dev.py
│   │       └── prod.py
│   │
│   ├── apps/                           # 业务应用（17个app）
│   │   │
│   │   ├── users/                      # 1. 用户模块
│   │   │   ├── models.py               # User, UserProfile
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   ├── permissions.py          # 角色权限类
│   │   │   └── urls.py
│   │   │
│   │   ├── projects/                   # 2. 项目模块
│   │   │   ├── models.py               # Project, ProjectMember
│   │   │   ├── serializers.py
│   │   │   ├── views.py
│   │   │   └── urls.py
│   │   │
│   │   ├── agents/                     # 3. 智能体模块
│   │   │   ├── models.py               # Agent, AgentVersion
│   │   │   ├── graph/                  # LangGraph设计
│   │   │   │   ├── state.py            # 状态定义
│   │   │   │   ├── nodes.py            # 节点定义
│   │   │   │   ├── edges.py            # 条件路由
│   │   │   │   └── builder.py          # 图构建
│   │   │   └── prompts/                # 提示词
│   │   │       └── defaults.py
│   │   │
│   │   ├── requirement_analysis/       # 4. 需求分析模块
│   │   │   ├── models.py               # RequirementDocument, RequirementAnalysis
│   │   │   ├── analyzer.py             # LLM分析器
│   │   │   ├── linkage_finder.py       # 联合功能识别
│   │   │   ├── version_tracker.py      # 版本追踪
│   │   │   └── online_doc/             # 在线文档适配器
│   │   │       ├── base.py
│   │   │       ├── tencent_doc.py
│   │   │       ├── feishu_doc.py
│   │   │       ├── notion_doc.py
│   │   │       └── yuque_doc.py
│   │   │
│   │   ├── case_generation/            # 5. 用例生成模块
│   │   │   ├── models.py               # CaseGenerationRecord
│   │   │   ├── generator.py            # 5轮生成器
│   │   │   ├── reviewer.py             # 5轮评审器
│   │   │   ├── automation_filter.py    # 自动化筛选
│   │   │   ├── screenshot_analyzer.py  # 截图识别
│   │   │   ├── data_preparer.py        # 数据构造
│   │   │   └── coverage.py             # 覆盖度计算
│   │   │
│   │   ├── business_linkage/           # 6. 业务联调模块
│   │   │   ├── models.py               # BusinessLinkage
│   │   │   ├── linkage_analyzer.py     # 链路识别
│   │   │   └── data_flow.py            # 数据流转
│   │   │
│   │   ├── knowledge/                  # 7. 知识库模块
│   │   │   ├── models.py               # KnowledgeBase, Document, QAPair, Embedding
│   │   │   ├── loader.py               # 文档加载
│   │   │   ├── splitter.py             # 分块
│   │   │   ├── embedding.py            # 向量化
│   │   │   └── retriever.py            # 混合检索
│   │   │
│   │   ├── skills/                     # 8. Skills模块
│   │   │   ├── models.py               # Skill
│   │   │   ├── manager.py              # Skill管理器
│   │   │   └── built_in/               # 内置Skills
│   │   │       ├── base.py
│   │   │       ├── api_test_skill.py
│   │   │       ├── ai_test_skill.py
│   │   │       ├── ui_test_skill.py
│   │   │       ├── app_test_skill.py
│   │   │       ├── perf_test_skill.py
│   │   │       └── case_gen_skill.py
│   │   │
│   │   ├── tests/                      # 9. 测试模块
│   │   │   ├── models.py               # TestCase, TestRun, TestResult, Evaluation
│   │   │   ├── executor/               # 执行器
│   │   │   │   ├── base.py
│   │   │   │   ├── api_executor.py
│   │   │   │   ├── ai_executor.py
│   │   │   │   ├── ui_executor.py
│   │   │   │   ├── app_executor.py
│   │   │   │   └── perf_executor.py
│   │   │   ├── generator/              # 代码生成器
│   │   │   │   ├── pytest_gen.py
│   │   │   │   ├── playwright_gen.py
│   │   │   │   ├── appium_gen.py
│   │   │   │   ├── locust_gen.py
│   │   │   │   ├── jmeter_gen.py
│   │   │   │   └── data_gen.py
│   │   │   └── jmeter/                 # JMeter专用
│   │   │       ├── jmx_generator.py
│   │   │       ├── jmx_reuser.py
│   │   │       ├── jtl_parser.py
│   │   │       └── jmeter_executor.py
│   │   │
│   │   ├── environments/               # 10. 环境管理模块
│   │   │   ├── models.py               # Environment
│   │   │   └── health_checker.py       # 健康检查
│   │   │
│   │   ├── notifications/              # 11. 通知中心模块
│   │   │   ├── models.py               # NotificationConfig, Record, Log
│   │   │   ├── services.py             # 通知服务
│   │   │   └── channels/               # 渠道实现
│   │   │       ├── base.py
│   │   │       ├── wechat.py
│   │   │       ├── dingtalk.py
│   │   │       ├── email.py
│   │   │       └── in_app.py
│   │   │
│   │   ├── git_integration/            # 12. Git集成模块
│   │   │   ├── models.py               # GitRepository, WebhookRecord
│   │   │   ├── views.py                # Webhook接收
│   │   │   └── analyzer.py             # 变更分析
│   │   │
│   │   ├── proactive/                  # 13. 主动建议模块
│   │   │   ├── models.py               # Suggestion
│   │   │   └── services.py             # 分析服务
│   │   │
│   │   ├── test_assets/                # 14. 测试资产模块
│   │   │   ├── models.py               # TestAssetTemplate
│   │   │   └── template_manager.py
│   │   │
│   │   ├── roi_metrics/                # 15. ROI度量模块
│   │   │   ├── models.py               # RoiMetric
│   │   │   └── dashboard.py            # 仪表盘数据
│   │   │
│   │   ├── reports/                    # 16. 报告模块
│   │   │   ├── models.py               # Report
│   │   │   └── generator.py            # 报告生成
│   │   │
│   │   └── configs/                    # 17. 配置模块
│   │       ├── models.py               # ModelConfig, PromptConfig
│   │       └── views.py
│   │
│   ├── core/                           # 核心公共模块
│   │   ├── llm/                        # LLM管理
│   │   │   ├── base.py                 # Provider基类
│   │   │   ├── manager.py              # 模型管理器
│   │   │   ├── router.py               # 模型路由
│   │   │   ├── factory.py              # 模型工厂
│   │   │   └── providers/              # 各Provider
│   │   ├── prompts/                    # 提示词管理
│   │   │   ├── manager.py
│   │   │   ├── merger.py
│   │   │   └── defaults.py
│   │   ├── tools/                      # 工具层
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   └── ...                     # 各工具实现
│   │   ├── memory/                     # 记忆系统
│   │   └── utils/                      # 工具函数
│   │       ├── logger.py
│   │       └── crypto.py
│   │
│   └── tasks/                          # Celery任务
│       ├── celery_app.py
│       ├── chat_tasks.py
│       ├── test_tasks.py
│       ├── knowledge_tasks.py
│       ├── report_tasks.py
│       ├── requirement_tasks.py
│       ├── case_gen_tasks.py
│       ├── environment_tasks.py
│       ├── notification_tasks.py
│       ├── git_tasks.py
│       ├── proactive_tasks.py
│       └── schedule.py
│
├── test_scripts/                       # 测试脚本目录
├── nginx/                              # Nginx配置
├── scripts/                            # 部署脚本
└── docs/                               # 文档
```


## 4. 数据库设计

### 4.1 表清单（共30张表）

| 序号 | 表名 | 所属模块 | 用途 |
|------|------|---------|------|
| 1 | users_user | 用户 | 用户账号 |
| 2 | users_userprofile | 用户 | 用户偏好 |
| 3 | projects_project | 项目 | 项目信息 |
| 4 | projects_projectmember | 项目 | 项目成员 |
| 5 | configs_modelconfig | 配置 | 模型配置 |
| 6 | configs_promptconfig | 配置 | 提示词配置 |
| 7 | agents_agent | 智能体 | 智能体配置 |
| 8 | requirement_document | 需求分析 | 需求文档 |
| 9 | requirement_analysis | 需求分析 | 分析结果 |
| 10 | case_generation_record | 用例生成 | 生成记录 |
| 11 | business_linkage | 业务联调 | 业务链路 |
| 12 | tests_testcase | 测试 | 测试用例 |
| 13 | tests_testrun | 测试 | 执行记录 |
| 14 | tests_testresult | 测试 | 执行结果 |
| 15 | tests_evaluation | 测试 | 评估结果 |
| 16 | environments_environment | 环境 | 测试环境 |
| 17 | notifications_config | 通知 | 通知配置 |
| 18 | notifications_record | 通知 | 通知记录 |
| 19 | notifications_log | 通知 | 发送日志 |
| 20 | git_repository | Git | 仓库配置 |
| 21 | git_webhookrecord | Git | Webhook记录 |
| 22 | knowledge_base | 知识库 | 知识库 |
| 23 | knowledge_document | 知识库 | 文档 |
| 24 | knowledge_qapair | 知识库 | 问答对 |
| 25 | knowledge_embedding | 知识库 | 向量 |
| 26 | skills_skill | Skills | 技能 |
| 27 | test_asset_template | 测试资产 | 资产模板 |
| 28 | roi_metric | ROI | 度量数据 |
| 29 | reports_report | 报告 | 报告 |
| 30 | proactive_suggestion | 主动建议 | 建议记录 |

### 4.2 关键表结构设计

#### 需求分析相关表

```
requirement_document（需求文档表）
├── id: UUID PK
├── project_id: FK → Project
├── title: VARCHAR(500)
├── version: VARCHAR(20)
├── source_type: VARCHAR(20)      -- file/online_link/screenshot/manual
├── source_url: VARCHAR(1000)
├── file_path: VARCHAR(1000)
├── content_text: TEXT
├── status: VARCHAR(20)           -- uploaded/parsing/analyzing/analyzed/failed
├── created_by: FK → User
└── created_at: TIMESTAMP

requirement_analysis（需求分析结果表）
├── id: UUID PK
├── document_id: FK → RequirementDocument
├── modules: JSONB                -- 功能模块拆解
├── functions: JSONB              -- 功能点
├── linkages: JSONB               -- 联合功能识别
├── test_points: JSONB            -- 测试点
├── coverage_report: JSONB        -- 覆盖度报告
└── created_at: TIMESTAMP
```

#### 用例生成相关表

```
case_generation_record（用例生成记录表）
├── id: UUID PK
├── project_id: FK → Project
├── document_id: FK → RequirementDocument
├── rounds: INT                   -- 确认轮次
├── total_cases: INT              -- 总用例数
├── auto_cases: INT               -- 可自动化数
├── manual_cases: INT             -- 需手动数
├── status: VARCHAR(20)           -- generating/reviewing/completed/failed
└── created_at: TIMESTAMP
```

#### 业务联调表

```
business_linkage（业务链路表）
├── id: UUID PK
├── project_id: FK → Project
├── name: VARCHAR(200)            -- 链路名称
├── steps: JSONB                  -- 链路步骤
├── dependencies: JSONB           -- 依赖关系
├── test_case_ids: JSONB          -- 关联用例
└── created_at: TIMESTAMP
```

#### 测试用例表（含自动化标注）

```
tests_testcase（测试用例表）
├── id: UUID PK
├── case_id: VARCHAR(50) UNIQUE
├── title: VARCHAR(500)
├── precondition: TEXT
├── steps: JSONB
├── input_data: JSONB
├── expected_result: TEXT
├── priority: VARCHAR(10)         -- P0/P1/P2/P3
├── case_type: VARCHAR(50)        -- function/boundary/exception/security/api/ai/ui/app/perf
├── is_automation: BOOLEAN        -- 是否可自动化
├── automation_difficulty: VARCHAR(10)  -- low/medium/high
├── automation_tech: VARCHAR(50)  -- pytest/playwright/appium/locust/jmeter
├── requirement_mapping: JSONB    -- 需求映射
└── created_at: TIMESTAMP
```

#### 测试环境表

```
environments_environment（测试环境表）
├── id: UUID PK
├── project_id: FK → Project
├── name: VARCHAR(50)             -- dev/test/staging/prod
├── base_url: VARCHAR(500)
├── database_config: JSONB
├── auth_config: JSONB
├── variables: JSONB
├── status: VARCHAR(20)           -- available/maintenance/unavailable
├── health_check_url: VARCHAR(500)
├── health_status: VARCHAR(20)    -- healthy/unhealthy/unknown
└── UNIQUE(project_id, name)
```

#### 通知相关表

```
notifications_config（通知配置表）
├── id: UUID PK
├── project_id: FK → Project
├── channel: VARCHAR(20)          -- wechat/dingtalk/email/in_app/feishu
├── webhook_url: VARCHAR(1000)
├── enabled: BOOLEAN
├── min_priority: VARCHAR(10)
├── frequency: VARCHAR(20)        -- instant/5min/hourly/daily
├── quiet_start: TIME
└── quiet_end: TIME
```


## 5. LangGraph智能体设计

### 5.1 状态定义

```
AgentState（智能体状态）
├── 对话信息
│   ├── messages: List[Message]       -- 对话历史
│   ├── user_input: str               -- 当前输入
│   ├── conversation_id: str          -- 会话ID
│   ├── project_id: str               -- 项目ID
│   └── user_id: str                  -- 用户ID
├── 环境信息
│   └── selected_environment: str     -- 测试环境
├── 理解结果
│   ├── intent: str                   -- 意图类型
│   ├── entities: Dict                -- 实体信息
│   └── clarified_questions: List     -- 澄清问题
├── 需求分析
│   ├── requirement_document_id: str  -- 文档ID
│   ├── requirement_analysis: Dict    -- 分析结果
│   └── case_generation: Dict         -- 用例生成结果
├── 检索结果
│   └── knowledge_context: List       -- 知识上下文
├── 规划结果
│   ├── plan: Dict                    -- 测试计划
│   ├── selected_skills: List         -- 选中Skills
│   └── execution_order: List         -- 执行顺序
├── 执行结果
│   ├── execution_results: List       -- 执行结果
│   └── execution_status: str         -- 执行状态
├── 打断控制
│   └── interrupt_signal: str         -- pause/stop/cancel
├── 反思结果
│   ├── analysis: Dict                -- 分析结果
│   ├── needs_replan: bool            -- 是否重规划
│   ├── should_learn: bool            -- 是否学习
│   ├── should_report: bool           -- 是否报告
│   └── should_notify: bool           -- 是否通知
└── 输出
    ├── final_report: Dict            -- 最终报告
    └── error_message: str            -- 错误信息
```

### 5.2 节点设计

| 节点 | 职责 | 输入 | 输出 |
|------|------|------|------|
| perceive | 感知用户输入 | user_input | messages |
| understand | 意图识别 | messages, prompt | intent, entities |
| retrieve | 知识检索 | user_input, intent | knowledge_context |
| plan | 任务规划 | intent, knowledge | plan, skills |
| decide | 决策路由 | intent, plan | 路由目标 |
| requirement_analysis | 需求分析 | document_id | analysis_result |
| case_generation | 用例生成 | analysis_result | cases |
| case_review | 用例评审 | cases | review_result |
| reflect | 结果反思 | execution_results | analysis |
| learn | 知识沉淀 | analysis | — |
| report | 报告生成 | analysis | final_report |

### 5.3 路由逻辑

```
decide节点根据intent路由：

intent = "requirement_analysis" → requirement_analysis节点
intent = "case_gen"             → case_generation节点
intent = "api_test"             → 接口测试执行节点
intent = "ai_test"              → AI测试执行节点
intent = "ui_test"              → UI测试执行节点
intent = "app_test"             → APP测试执行节点
intent = "perf_test"            → 性能测试执行节点
intent = "other"                → reflect节点

requirement_analysis → case_generation → case_review → reflect
reflect → learn → report → END
```

### 5.4 打断处理设计

```
任意节点执行中，检测到interrupt_signal：
- pause：暂停当前节点，保留状态，等待用户指令
- stop：停止执行，保留已完成结果，跳转到report节点
- cancel：取消执行，清理临时数据，返回END
```


## 6. 多模型管理设计

### 6.1 模块职责

| 组件 | 职责 |
|------|------|
| ModelManager | 加载、获取、切换、路由模型 |
| ModelFactory | 根据配置创建模型实例 |
| ModelRouter | 按任务类型/成本/质量路由 |
| Providers | 各模型提供商适配 |

### 6.2 Provider设计

```
BaseModelProvider（抽象基类）
├── create_model(config) → LangChain模型实例
├── test_connection(config) → 连通性测试
└── get_capabilities() → 模型能力

具体Provider：
├── OpenAIProvider
├── AnthropicProvider
├── QwenProvider（通义千问）
├── DeepSeekProvider
├── CustomProvider（OpenAI兼容）
└── LocalProvider（Ollama/vLLM）
```

### 6.3 路由策略设计

| 策略 | 触发条件 |
|------|---------|
| 默认模型 | 用户未指定时 |
| 按任务路由 | 不同task_type使用不同模型 |
| 按成本路由 | 简单任务用便宜模型 |
| 按质量路由 | 复杂任务用强模型 |
| 故障切换 | 主模型失败切备用 |
| 用户指定 | 对话中指定 |


## 7. 提示词管理设计

### 7.1 层级合并设计

```
优先级（从高到低）：
1. 即时指定（用户当次对话要求）
2. 场景级（特定测试类型）
3. 项目级（特定项目）
4. 全局默认（平台级）

合并规则：
- 身份定义类：高层覆盖低层
- 规则约束类：高层优先，低层补充
- 补充说明类：全部保留
```

### 7.2 默认提示词场景清单

| 场景 | 用途 |
|------|------|
| default | 全局默认 |
| requirement_analysis | 需求分析 |
| case_gen | 用例生成 |
| case_review | 用例评审 |
| api_test | 接口测试 |
| ai_test | AI测试 |
| ui_test | UI测试 |
| app_test | APP测试 |
| perf_test | 性能测试 |
| screenshot_analysis | 截图识别 |
| report_gen | 报告生成 |


## 8. 知识库与检索设计

### 8.1 检索架构

```
查询输入
    ↓
查询理解（意图/实体/关键词）
    ↓
┌─────────┬─────────┬─────────┐
│ 语义检索 │ 关键词       │ 元数据  │
│ (pgvector)│ (PostgreSQL FTS rank) │ 过滤 │
└─────────┴─────────┴─────────┘
    ↓
融合排序（去重+分数排序）
    ↓
Top-K结果
```

### 8.2 知识审核流程

```
自动提取 → 待审核 → 人工审核 → 入库/拒绝/修改/暂缓
```

### 8.3 RAG 二阶段总体架构

RAG 二阶段不是把 LlamaIndex 直接嵌入业务 Service，而是建立一个受权限约束的适配层。Django ORM、PostgreSQL 和审核状态仍是唯一业务真理源，LlamaIndex 只接收已经通过权限过滤的文档节点和检索请求。

```text
用户查询 / 智能体上下文
          ↓
RAG Query Service
  ① 解析查询与权限上下文
  ② 生成查询 Embedding（knowledge_model）
  ③ PostgreSQL FTS 关键词召回
  ④ pgvector 语义召回
  ⑤ 元数据和审核状态过滤
  ⑥ 分数归一化 / RRF 融合 / 去重
  ⑦ 可选 rerank
  ⑧ 上下文截断与引用组装
          ↓
统一 RetrievalResult / Citation
          ↓
知识库 REST API 或 LangGraph retrieve_node
```

数据边界固定为：

- Django 负责用户、项目、知识库、文档、问答、审核、成员权限和索引任务状态；
- PostgreSQL + pgvector 负责向量存储和近邻查询；PostgreSQL 全文检索负责关键词候选；
- LlamaIndex 负责文档节点、索引/检索器适配和未来连接器扩展，不直接决定项目范围和审核状态；
- Redis/Celery 负责异步解析、Embedding、索引和重建任务，不作为知识事实存储；
- LangGraph 只消费统一检索结果，不复制另一套 RAG 权限和排序逻辑。

### 8.4 RAG 领域对象与数据模型

现有 `KnowledgeBase`、`Document`、`QAPair` 和 `Embedding` 保留。RAG 二阶段在不破坏历史数据的前提下补充以下概念，字段名称可在 T133 兼容性验证后最终锁定：

```text
KnowledgeIndex
├── knowledge_base_id / project_id
├── source_type / source_id
├── embedding_model / embedding_dimension
├── index_version
├── status: pending | building | ready | partial | failed | stale
├── source_checksum / chunking_policy
├── last_error_code / last_error_message（脱敏）
├── started_at / completed_at
└── created_by / created_at

EmbeddingChunk（扩展现有 Embedding）
├── document_id 或 qa_pair_id（二选一）
├── content / normalized_content
├── vector: pgvector
├── search_text: PostgreSQL FTS 需要的规范化文本
├── chunk_index / source_locator
├── index_version / model_name / dimensions
└── review_snapshot / metadata
```

设计决策：

1. 不直接把 JSON 向量字段改成不可逆删除。先增加新向量存储和索引版本，完成回填与对比后再决定旧字段只读保留或移除。
2. 同一索引版本只允许一种 Embedding 模型和维度，避免不同维度向量混查。
3. 文档内容、审核状态或项目归属发生变化时，旧索引标记为 `stale`，不能继续作为默认有效索引。
4. 删除或审核撤回优先通过数据库过滤立即阻断召回，再异步清理物理向量，避免等待清理任务造成数据泄漏。
5. 所有索引操作必须幂等，重复任务按内容校验和、来源 ID、分块策略和索引版本去重。

P0 采用一种固定维度的生产 Embedding 配置，`VectorField(dimensions=...)` 与近邻索引按该维度建立。更换模型或维度时不得原地覆盖字段：必须创建新的索引版本和对应的向量存储（独立表、分区或经验证的独立列），新旧版本并存并分别评测，最后通过 `active_index_version` 原子切换。不同维度禁止进入同一查询、融合或 rerank 批次。

### 8.5 文档到索引的生命周期

```text
Document.ready + review approved
          ↓
计算 source_checksum 与 chunking_policy
          ↓
创建 KnowledgeIndex(building)
          ↓
规范化文本 / 分块 / source_locator
          ↓
调用 EmbeddingProvider
          ↓
批量写入 pgvector 与 FTS 数据
          ↓
抽样查询和计数校验
          ↓
原子切换 active index_version
          ↓
KnowledgeIndex.ready
```

- 新版本索引未完成前，旧的 `ready` 版本继续提供服务；新版本成功后再原子切换。
- 单个分块失败时记录分块级错误；是否允许 `partial` 由策略决定，默认不把部分索引标记为完整可用。
- Embedding 供应商超时、额度不足、能力不匹配或网络错误必须分类记录并可重试；重试不得重复计费无意义请求。
- Celery 任务必须支持任务状态查询、取消/过期保护和重复提交幂等；API 不应同步等待整库索引完成。
- 全量或大批量索引必须先执行 dry-run 预估，返回文档数、分块数、预计模型调用量、费用区间、预计耗时和影响范围；超过预算、并发或单次规模上限时，任务只能进入 `awaiting_confirmation` 或安全拒绝。
- 新索引质量不达标、构建失败或上线后异常时，管理员可以将 `active_index_version` 原子回滚到上一版；回滚操作必须记录操作者、原因、影响范围，并在查询时重新执行权限过滤。

### 8.6 Embedding、关键词和混合检索设计

#### 8.6.1 EmbeddingProvider 契约

```python
embed_texts(texts, model_config, *, timeout, batch_size) -> EmbeddingBatch
```

契约必须包含模型名称、固定维度、批次结果、失败分块、供应商错误分类、耗时、费用摘要和数据外发决策。真实 Provider 通过现有模型配置和 `knowledge_model` 路由选择；离线 HashVectorizer 仅用于测试夹具或迁移验证，并在结果中明确标记 `offline_test`。

Embedding 调用前必须执行 `sensitive_scan`：识别 API Key、密码、Token、个人信息、内网凭据和组织禁止外发内容。策略结果只能是 `allow_external`、`redact_then_allow`、`local_only` 或 `deny`；外部 Provider 不得收到被策略禁止的原文。策略命中、脱敏字段类别、供应商、地域和操作者确认写入审计，不写入原始敏感值。

#### 8.6.2 候选召回

- 语义召回：使用 pgvector 的近邻距离和索引，先按 project、knowledge_base、审核和 active index_version 过滤；
- 关键词召回：P0 使用 PostgreSQL `SearchVector`、`SearchQuery`、`SearchRank` 或等价数据库能力，不在业务层全表加载；这称为 PostgreSQL FTS 排名，不无条件宣称为 BM25；
- 两路召回分别保留原始分数和召回来源，避免在融合前丢失可解释性；
- 默认候选数量大于最终 Top-K，融合后再截断；Top-K 上限由后端校验。

#### 8.6.3 融合与重排序

```text
semantic_candidates + keyword_candidates
                ↓
权限/审核/版本二次过滤
                ↓
按 chunk/source 去重
                ↓
分数归一化或 Reciprocal Rank Fusion
                ↓
可选 reranker（knowledge_model 的 rerank 能力）
                ↓
ContextPack + Citation[]
```

首版采用可解释的加权或 RRF 配置，不引入训练型排序器。只有在离线评测证明混合排序稳定后，才允许启用 reranker；reranker 失败保留混合结果并返回 `rerank_failed` 状态。

真正 BM25 不属于 P0 的默认依赖。若后续引入数据库扩展，必须单独完成兼容性、备份恢复、查询性能、运维和排序收益评估，不能把扩展安装作为 RAG 基础任务的隐式前置条件。

### 8.7 统一结果与引用契约

```json
{
  "query": "用户原始问题",
  "mode": "hybrid",
  "index_version": "...",
  "results": [
    {
      "citation_id": "kb-doc-chunk-v1",
      "knowledge_base_id": "...",
      "project_id": "...",
      "document_id": "...",
      "title": "接口规范",
      "content": "受限证据片段",
      "source_locator": {"page": 3, "chunk_index": 4},
      "retrieval_sources": ["semantic", "keyword"],
      "score": 0.87,
      "review_status": "approved"
    }
  ],
  "evidence_sufficient": true,
  "warnings": []
}
```

结果契约禁止返回 API Key、凭据、未脱敏环境变量和未授权文档正文。`content` 必须经过长度限制和敏感信息处理；完整原文只允许通过再次执行权限校验的详情接口读取。

### 8.8 LlamaIndex 适配边界

建议建立以下模块，实际文件在 T137 才创建：

```text
backend/core/rag/
├── contracts.py       # Node、Query、Result、Citation、错误契约
├── providers.py       # Embedding/Rerank Provider 适配协议
├── nodes.py           # Django Document/QAPair → 受控节点
├── indexer.py         # 索引构建、版本和幂等控制
├── retriever.py       # pgvector、关键词、LlamaIndex检索适配
├── fusion.py          # 去重、归一化、RRF/加权融合
├── context.py         # 上下文长度预算和引用组装
└── errors.py          # 脱敏错误分类
```

LlamaIndex 适配器必须满足：

1. 输入节点只能来自已经通过 Django 权限、项目和审核过滤的查询集；
2. 适配器不能自行读取整个表、绕过 serializer 或缓存跨用户的完整上下文；
3. LlamaIndex 不可用时可切换到原生 Django/pgvector 检索，但切换原因必须进入结果警告和审计；
4. 版本升级必须通过 T133 的兼容性测试，不能使用未锁定的浮动依赖；
5. 适配器异常只能导致当前请求失败或安全降级，不得改变审核状态、权限或任务生命周期。

### 8.9 LangGraph 接入方式

RAG 在智能体中的调用仅通过统一 `RAGQueryService`：

```text
AgentState.user_input + project_context + permission_context
                         ↓
                 retrieve_node
                         ↓
knowledge_context + citations + evidence_sufficient + warnings
                         ↓
                 plan/decide/report
```

`retrieve_node` 不直接导入 LlamaIndex，不直接操作 Embedding 表，也不自行实现权限过滤。没有知识相关意图时跳过检索；证据不足时进入澄清或人工确认分支；检索故障时保留错误事件，不把空列表解释为“没有相关事实”。

智能体回答必须使用独立的证据型回答契约：

```json
{
  "answer": "基于证据生成的回答",
  "grounding_status": "grounded | insufficient_evidence | retrieval_failed",
  "claims": [
    {"text": "关键结论", "type": "fact | inference | needs_confirmation", "citation_ids": ["..."]}
  ],
  "citations": [],
  "warnings": []
}
```

回答生成器不得自行查询知识表或重新召回；它只能消费 `ContextPack` 和 `Citation[]`。当关键结论没有引用、引用不足或引用状态失效时，必须降级为证据不足/澄清，而不是输出无依据的确定性表述。文档中的提示词、指令或恶意内容只能作为待分析文本，不能改变系统提示词、权限或工具策略。

### 8.10 安全、权限和可观测性

- 权限过滤顺序固定为用户身份 → 项目成员关系 → 知识库范围 → 审核状态 → 索引版本 → 结果详情；
- 跨项目查询、归档知识库、未审核内容、已撤销成员和过期索引必须有自动化零泄漏测试；
- 查询日志只记录查询摘要、项目 ID、索引版本、结果数量、耗时和错误码，不记录完整敏感查询或完整文档正文；
- 审计记录模型、Embedding 供应商、索引版本、召回路径、rerank 状态和失败阶段，费用字段不记录密钥；
- 外部模型和 LlamaIndex 请求有超时、重试上限、熔断/限流和错误脱敏；
- 知识内容发送到外部 Embedding 或进入模型上下文前都执行敏感信息检测和长度预算；外部发送前展示供应商、地域、内容类别和脱敏结果，未经授权只能使用本地路径或阻止；文档中的提示词不能改变系统权限或工具策略。
- 索引任务使用预算、并发、单批大小和超时限制；全量任务在 dry-run 与管理员确认前不能启动，取消和超预算拒绝必须写入审计。
- 查询缓存（若启用）必须以用户/项目/知识库/索引版本/权限摘要为隔离键，成员权限变化或索引切换时失效，禁止复用跨项目上下文。

### 8.11 评测与发布门禁

RAG 发布前必须有人工标注集，至少覆盖：精确术语、同义问题、跨项目同名对象、版本差异、未审核内容、无答案问题和恶意提示词注入。每次索引策略、Embedding 模型、融合权重或分块策略变化，都要重新评测。

最低指标：权限未授权召回为 0；关键词测试集命中率 ≥95%；混合检索 Recall@5 ≥90%；有依据回答引用完整率 ≥98%；无依据拒答准确率 ≥90%；普通检索 P95 ≤2 秒。未达标时只能标记为实验能力，不能作为智能体默认知识来源。

### 8.12 部署与依赖决策

- PostgreSQL 16 必须启用 pgvector 扩展；远程 Compose 保留扩展初始化和健康检查；
- 本地 SQLite 继续用于快速单元测试，但 pgvector、FTS 和真实 Provider 必须有 PostgreSQL 集成测试；
- LlamaIndex 及其子包只在 T133 兼容性验证后加入锁定依赖，禁止一次性安装全部可选集成包；
- 索引和重建通过 Celery/Redis 执行，必须设置任务超时、并发上限和批量大小；
- 全量重建必须支持 dry-run 预估、管理员确认、预算上限、并发限制、取消和上一版回滚；
- 新增环境变量、数据库扩展、依赖和迁移必须同时记录在项目状态和完成报告；
- 生产部署先以单一 Embedding 模型和混合检索上线，后续模型、连接器和 reranker 通过适配器扩展。


## 9. 需求分析与用例生成设计

### 9.1 完整链路设计

```
需求输入（文件/在线链接/截图/手动）
    ↓
文档解析（PDF/Word/Excel/Markdown/Swagger/在线文档/OCR）
    ↓
需求深度分析（功能拆解/关联识别/流程梳理/数据流转）
    ↓
联合功能识别（跨模块展示/依赖/状态联动/数据联动）
    ↓
测试点分析（正向/边界/异常/安全/联动/性能）
    ↓
用例生成（5轮对比确认）
    ↓
用例评审（5轮对比评审）
    ↓
自动化筛选（可自动化判断/难度/技术栈/优先级）
    ↓
覆盖度报告（需求-测试点-用例映射）
```

### 9.2 在线文档适配器设计

```
OnlineDocAdapter（抽象基类）
├── match(url) → bool：判断是否匹配
├── fetch(url) → str：获取文档内容
└── parse(content) → Dict：解析结构

具体适配器：
├── TencentDocAdapter：docs.qq.com
├── FeishuDocAdapter：feishu.cn
├── NotionAdapter：notion.so
├── YuqueAdapter：yuque.com
├── ConfluenceAdapter：confluence
├── SwaggerAdapter：swagger.json
└── GenericWebAdapter：通用网页
```

### 9.3 截图识别设计

```
ScreenshotAnalyzer
├── 输入：图片文件路径
├── 处理：
│   ├── 视觉模型识别页面元素
│   ├── OCR识别文字和错误信息
│   ├── 提取可测试功能点
│   └── 分析交互逻辑
└── 输出：元素列表 + 错误信息 + 测试点 + 生成用例
```


## 10. 业务联调设计

### 10.1 链路识别设计

```
输入：接口文档列表
    ↓
LLM分析接口间业务调用关系
    ↓
识别：
├── 登录依赖（Token传递）
├── 数据依赖（ID传递）
├── 状态流转（订单状态/支付状态）
└── 业务顺序（必须先A后B）
    ↓
输出：业务链路列表
```

### 10.2 数据流转设计

```
链路：登录 → 创建订单 → 支付 → 退款

数据流转：
登录响应.token → 创建订单请求头
创建订单响应.order_id → 支付请求体
支付响应.pay_id → 退款请求体
退款响应.refund_id → 库存回滚验证
```


## 11. Skills技能系统设计

### 11.1 Skill定义结构

```
Skill
├── name: 技能名称
├── version: 版本
├── description: 描述
├── category: 分类（core/specialized/auxiliary/custom）
├── triggers: 触发条件
│   ├── explicit: 用户明确触发词
│   ├── implicit: 自动触发条件
│   └── prohibited: 禁止触发条件
├── capabilities: 能力列表
├── tools: 所需工具
├── knowledge: 所需知识
├── input_schema: 输入定义
└── output_schema: 输出定义
```

### 11.2 智能调度设计

```
用户输入 → 意图识别 → 核心Skill必选 → 关联Skill推荐 → 用户确认 → 执行
```


## 12. 测试执行引擎设计

### 12.1 执行器架构

```
BaseExecutor（抽象基类）
├── 环境感知
├── 工作目录管理
├── pytest执行
└── 结果解析

具体执行器：
├── APIExecutor：接口测试（即时/脚本/完整三模式）
├── AIExecutor：AI测试（8维度评估）
├── UIExecutor：UI测试（Playwright）
├── AppExecutor：APP测试（Appium+adb）
└── PerfExecutor：性能测试（JMeter+Locust双引擎）
```

### 12.2 性能测试双引擎设计

```
引擎选择策略：
1. 已有JMX脚本 → JMeter复用
2. 用户指定引擎 → 按指定
3. 并发>5万 → Locust
4. 复杂协议 → JMeter
5. 默认 → Locust

JMeter路径：JMX生成/复用 → 执行 → JTL解析 → 统一格式
Locust路径：代码生成 → 执行 → CSV解析 → 统一格式
```


## 13. 代码自动生成器设计

| 生成器 | 用途 | 输出 |
|--------|------|------|
| PytestGenerator | 接口测试代码 | pytest+requests+数据驱动 |
| PlaywrightGenerator | UI测试代码 | Playwright+POM |
| AppiumGenerator | APP测试代码 | Appium+pytest |
| LocustGenerator | 性能测试脚本 | Locust Python |
| JMXGenerator | JMeter脚本 | JMX XML |
| DataGenerator | 测试数据 | 边界值/特殊字符/大数据量 |


## 14. 测试环境管理设计

### 14.1 环境类型与权限

| 环境 | 权限 |
|------|------|
| dev | 开发者可测 |
| test | 测试者可测 |
| staging | 负责人审批 |
| prod | 管理员审批 |

### 14.2 健康检查设计

```
定时检查（每5分钟）→ 检查health_check_url → 更新health_status → 异常通知
```


## 15. Git集成设计

### 15.1 自动触发流程

```
Git提交 → Webhook接收 → 验证Secret → 解析提交信息
    → 变更分析（影响模块） → 推荐用例 → 选择环境
    → 执行测试 → 分析结果 → 推送通知
```

### 15.2 变更分析设计

```
变更文件列表 → 映射到功能模块 → 推荐关联用例 → 评估风险等级
```


## 16. 通知中心设计

### 16.1 渠道设计

| 渠道 | 实现方式 |
|------|---------|
| 企业微信 | Webhook Markdown消息 |
| 钉钉 | Webhook Markdown消息 |
| 邮件 | SMTP HTML |
| 平台内 | 站内信 |
| 飞书 | Webhook（P1） |

### 16.2 发送流程

```
触发 → 级别判断 → 静默判断 → 偏好判断 → 频率判断
    → 选择渠道 → 渲染模板 → 发送 → 记录日志
    → 失败重试3次 → 降级平台内消息
```


## 17. 主动建议引擎设计

| 触发场景 | 分析方式 |
|---------|---------|
| Git变更 | Webhook触发分析 |
| 环境异常 | 健康检查发现 |
| 质量趋势 | 定期统计通过率 |
| 性能劣化 | 监控P99趋势 |
| 缺陷集中 | 统计模块缺陷数 |
| 定期报告 | 每日/每周定时 |


## 18. 测试资产与ROI设计

### 18.1 测试资产

| 模板类型 | 说明 |
|---------|------|
| 用例集模板 | 高质量用例集跨项目复用 |
| 策略模板 | 不同项目类型测试策略 |
| 缺陷模式 | 历史缺陷模式库 |

### 18.2 ROI度量

| 指标 | 计算方式 |
|------|---------|
| 时间节省 | 人工预计耗时 vs 平台实际耗时 |
| 缺陷效率 | 缺陷数 / 测试时间 |
| 用例质量 | AI生成 vs 人工创建对比 |


## 19. Celery异步任务设计

### 19.1 任务清单

| 任务 | 用途 | 触发方式 |
|------|------|---------|
| process_chat_message | 对话处理 | 用户发送消息 |
| execute_test_task | 测试执行 | 用户触发/Git触发 |
| analyze_requirement | 需求分析 | 用户上传文档 |
| generate_cases | 用例生成 | 分析完成 |
| check_environments | 环境健康检查 | 每5分钟定时 |
| send_notification | 通知发送 | 事件触发 |
| analyze_git_webhook | Git变更分析 | Webhook |
| generate_suggestions | 主动建议 | 每10分钟定时 |
| generate_daily_report | 每日报告 | 每天定时 |


## 20. 前端架构设计

### 20.1 页面清单（20个）

| 页面 | 功能 |
|------|------|
| LoginView | 登录 |
| ChatView | 对话主界面 |
| DashboardView | 仪表盘 |
| AgentManageView | 智能体管理 |
| KnowledgeBaseView | 知识库 |
| SkillsView | Skills管理 |
| TestCaseView | 测试用例 |
| TestRunView | 测试执行 |
| ReportView | 报告 |
| ModelConfigView | 模型配置 |
| PromptConfigView | 提示词配置 |
| EnvironmentView | 环境管理 |
| GitIntegrationView | Git集成 |
| NotificationCenter | 通知中心 |
| RequirementAnalysisView | 需求分析 |
| CaseGenerationView | 用例生成 |
| CoverageReportView | 覆盖度报告 |
| ROIView | ROI仪表盘 |
| ProjectManageView | 项目管理 |
| SystemSettingsView | 系统设置 |

### 20.2 状态管理（Pinia Stores）

| Store | 管理内容 |
|-------|---------|
| user | 用户信息、Token |
| chat | 对话消息、SSE状态 |
| agent | 智能体配置 |
| knowledge | 知识库数据 |
| test | 测试任务、结果 |
| environment | 环境列表、状态 |
| notification | 通知列表、配置 |
| requirement | 需求分析结果 |
| caseGen | 用例生成状态 |
| roi | ROI数据 |

### 20.3 样式方案（纯CSS）

```
styles/
├── variables.css    -- CSS变量（颜色/字体/间距）
├── theme.css        -- 主题样式
├── chat.css         -- 对话气泡样式
├── components.css   -- 通用组件样式
└── index.css        -- 全局入口
```


## 21. API接口设计

### 21.1 接口分组

| 分组 | 前缀 | 主要接口 |
|------|------|---------|
| 认证 | /api/auth/ | 登录、注册、获取用户信息 |
| 用户 | /api/users/ | 用户CRUD、偏好设置 |
| 项目 | /api/projects/ | 项目CRUD、成员管理 |
| 智能体 | /api/agents/ | 智能体CRUD |
| 对话 | /api/chat/ | 发送消息、SSE流、历史 |
| 需求分析 | /api/requirement/ | 上传文档、分析、结果 |
| 用例生成 | /api/case-gen/ | 生成、评审、筛选 |
| 知识库 | /api/knowledge/ | CRUD、检索、审核 |
| Skills | /api/skills/ | CRUD |
| 测试 | /api/tests/ | 用例CRUD、执行、结果 |
| 环境 | /api/environments/ | CRUD、健康检查 |
| 通知 | /api/notifications/ | 配置、列表、已读 |
| Git | /api/git/ | 仓库配置、Webhook |
| 报告 | /api/reports/ | 报告列表、详情、导出 |
| 模型 | /api/models/ | 模型CRUD、测试连接 |
| 提示词 | /api/prompts/ | 提示词CRUD、测试 |
| 资产 | /api/assets/ | 模板管理 |
| ROI | /api/roi/ | 度量数据 |


## 22. 服务器部署方案

> 本地开发阶段不使用Docker。腾讯云服务器使用隔离的Docker Compose联调环境；公司服务器的操作系统、进程托管及基础服务提供方式在上线前另行确认。

### 22.1 服务清单

| 服务 | 推荐实现 | 用途 |
|------|------|------|
| PostgreSQL | PostgreSQL 16 + pgvector | 数据库+向量 |
| Redis | Redis 7 | 缓存+队列 |
| backend | Django+Gunicorn（Linux服务器） | API服务 |
| celery_worker | Celery 5.4 | 异步任务 |
| celery_beat | Celery 5.4 | 定时任务 |
| frontend | Vue3静态构建产物 | Web前端 |
| JMeter | 服务器安装（可选） | 性能测试 |
| Nginx | 公司现有或服务器安装 | 反向代理 |

### 22.2 持久化目录

| 目录/存储 | 用途 |
|------|------|
| postgres_data | 数据库数据 |
| redis_data | Redis数据 |
| uploads_data | 上传文件 |
| static_data | 静态文件 |
| test_scripts | 测试脚本 |

### 22.3 模型供应商出网与代理硬门禁

模型供应商请求的唯一可信发起方是后端 Django、Celery Worker 或明确登记的模型服务进程。前端浏览器的网络能力不属于模型调用链路，不能作为服务器连通性的替代证明。

部署目标必须为上述每个实际发起进程建立出网配置：

1. 直连模式：供应商域名、地域地址和 TCP 443 通过服务器出口策略允许，DNS、TLS 证书链、SNI 和系统时间正常；
2. 代理模式：通过服务进程环境注入 `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` 或等价的受控配置，代理认证信息只进入进程环境或密钥管理系统，不进入仓库和日志；
3. 容器模式：`backend`、`celery_worker` 和需要模型调用的任务容器分别验证代理继承和 DNS，不假设 frontend 或宿主机配置会自动传入；
4. 网络策略：只允许目标供应商所需的最小出站范围，禁止为了连接测试关闭整体防火墙或安全策略；
5. 预检与真实验证：先做 DNS/TCP/TLS/代理路径预检，再使用真实模型名和有效 Key 执行一次不带项目数据的短调用。预检通过但实际调用失败时，必须保留供应商 HTTP、鉴权、额度、地域和模型能力的分层错误。

模型基础地址不能直接作为任意出站目标使用。请求前必须校验供应商域名/端口白名单，并对 DNS 解析结果执行回环、RFC1918、RFC6598、链路本地、广播、保留地址和云元数据地址拦截；连接阶段应固定已校验的解析结果或再次校验，防止 DNS rebinding。禁止通过重定向、代理自动转发或 IPv6 地址绕过目标校验。管理员权限只解决配置授权，不取消目标安全校验。

连接测试 API 应返回脱敏的失败阶段，例如 `dns_failed`、`tcp_blocked`、`tls_failed`、`proxy_unavailable`、`provider_http_error`、`auth_failed`、`quota_exhausted` 或 `model_capability_mismatch`；历史 `local_network_blocked` 作为兼容错误码保留，并归入 TCP/本机网络阻断阶段。这些错误码由 T146 在 Service、REST Serializer/响应和前端状态之间统一，不得把所有网络问题压缩为一个不可行动的“测试未通过”。健康检查和部署验收必须由与线上相同的 Django/Celery 运行身份执行，不能用浏览器或运维人员电脑的 curl 结果代替。

T145 只负责目标环境的 DNS/TCP/TLS/代理路径预检和运行身份验证；T146 负责目标安全校验、错误分类、REST 契约和前端反馈。T145 预检不得调用模型生成或 Embedding 接口；明确授权的真实短调用只在目标环境最终验收时执行一次，不自动重试、不携带项目数据。

代理配置必须分别注入 Django Web、Celery Worker 和需要模型调用的任务进程。部署模板应显式列出 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 的来源、作用范围、认证凭据注入、CA 证书和轮换方式；不能假设写入项目 `.env` 就会被所有启动脚本读取，也不能把带用户名密码的代理 URL 提交到仓库或日志。

T145 + T146 是跨模型功能和 RAG 生产验收的硬门禁。没有通过目标环境出网验证和目标地址安全校验时，系统可以继续运行 CRUD、离线测试和模拟 Provider，但必须把真实模型能力标记为“环境未就绪”，不得宣称已完成连接测试或生产验收。禁止使用定时任务自动调用收费模型作为健康检查；如需状态探测，应使用无费用网络预检或管理员手动触发的短调用，并设置结果有效期。

### 22.4 用户开通与规范访问入口

平台权限采用“平台角色 + 项目成员角色”两层模型，但产品必须提供连续的管理员操作链：账号邀请/开通、激活、平台角色分配、加入项目、项目角色分配、访问验证和撤销。不得通过共享管理员账号或管理员查看明文密码完成开通。

生产部署必须显式配置规范用户入口：

- `PUBLIC_APP_URL`：用户浏览器访问的唯一规范地址，优先 HTTPS 域名，无域名时才允许公网 IP 加映射端口；
- `PUBLIC_API_URL`：仅在前后端分离且非同源代理时使用，默认不直接暴露给普通用户；
- 可选内部运维地址：仅管理员或运维使用，不作为用户邀请地址。

系统不得通过枚举网卡自动选择或展示所有 IP。Docker 网络地址、数据库/Redis 地址、后端监听地址、SSH 地址和回环地址不属于用户访问入口。管理员工作台应读取显式配置，展示协议、主机、端口、访问范围、TLS/健康状态和最近检查时间，并生成基于该入口的邀请链接。

访问入口验收必须覆盖公网入口、内网入口、错误端口、反向代理、前端可达但 API 不可达、邀请链接过期和用户激活失败；任何情况下都不得把内部服务地址或凭据返回给普通用户。

### 22.5 供应商官方模型目录与选择器

模型选择器不能依赖用户手工记忆模型名称，也不能由前端直接请求供应商官网。模型目录由后端目录服务统一获取、规范化、缓存和审计。

目录来源按以下优先级处理：

1. 供应商官方模型目录 API；
2. 平台维护的官方目录快照，必须记录供应商来源、版本、更新时间和维护人；
3. 当前自定义端点返回的模型列表，仅能标记为“端点声明”，不能等同于供应商官网全量支持。

每个目录项至少包含 `provider`、`model_id`、展示名、协议、能力集合、版本/生命周期、来源、同步时间、过期时间和状态。状态至少区分 `catalog_listed`、`credential_accessible`、`endpoint_callable`、`stale`、`unsupported`，不得将目录存在直接转换为可调用。

目录服务必须支持按 Provider、协议、模型能力、项目功能和端点过滤；需求分析、视觉分析、聊天、Embedding 等入口只能展示能力匹配的模型。刷新由 Django/Celery 后端发起，复用统一网络安全校验、代理、超时、错误分层和审计链路；前端不得直接携带 Key 访问供应商。

官方目录不可获取时，保留最近一次目录并显示过期时间、失败阶段和手工模型 ID 入口。自定义 Provider、本地 Ollama/vLLM 或无公开目录的供应商不得生成“官网全部模型”的假数据；只能展示端点声明或管理员维护的目录快照。模型目录响应不得包含 Key、Authorization、代理凭据、完整敏感 URL 或原始供应商错误。

## 22.6 长输入与长结构化输出运行时

需求分析、用例生成/评审、报告和智能体结构化节点共用长内容运行时，不在各业务模块内分别实现“加大 token 后再重试”。当前 `structured_max_tokens=8192` 仅是有上限的短期保护值，不代表任意长度输入都能由一次调用完成。

### 运行时组件

- `ContextBudgetPlanner`：根据模型上下文窗口、输入估算、输出 Schema、供应商上限、费用和超时策略生成分段计划；
- `StructuredBatchExecutor`：按段执行结构化调用，统一处理续接游标、`finish_reason`、超时、取消、幂等键和受控重试；
- `StructuredResultMerger`：按稳定业务 ID 合并、去重、校验必填字段和证据引用，记录每条结果来自哪些段；
- `GenerationRun`/`GenerationSegment`：持久化总体状态、段状态、路由快照、Schema 版本、模型响应结束原因、重试次数、费用状态和 trace ID；不得保存 Key、Authorization 或不必要的完整敏感原文。

### 分段与合并契约

每个分段计划至少包含 `run_id`、`segment_id`、输入来源 ID、证据 ID 列表、预算、续接游标和幂等键。每段结构化响应至少包含 `schema_version`、`segment_id`、`is_final`、`continuation` 和业务结果集合。收到长度截断、无效 JSON 或可恢复供应商错误时，只能进入明确的续接、重分段或单段重试状态，不能直接写入完整结果。

合并器必须保持确定性：同一业务 ID只产生一个有效实体；冲突字段按 Schema 定义进入冲突记录，不静默覆盖；所有最终实体可反查到来源段、模型路由和调用阶段。部分完成结果只能以 `partial` 状态供用户查看，不能标记为 `model_verified` 或进入完整统计。

### 统一业务边界

运行时由需求分析、用例生成、五轮评审、报告生成和智能体结构化节点复用。REST 返回总体状态、当前段、已完成段、可重试段和错误码；前端提供继续、单段重试、取消和查看部分结果入口。任何自动重试必须有次数/费用边界和幂等保护，禁止因解析失败形成重试风暴或隐式跨供应商切换。


## 23. 扩展性设计

### 扩展目录基线（按对应任务创建）

```text
backend/core/
├── rag/                    # LlamaIndex适配器；领域模型仍由Django管理
├── mcp/                    # MCP client/server registry、策略与审计
├── runtimes/               # AgentRuntimeAdapter及可选CrewAI适配器
└── hitl/                   # LangGraph中断、审批、checkpoint与恢复服务
```

上述目录按对应任务建立，不得因文档出现而提前创建空模块或安装全部依赖。`core/rag` 属于阶段24的 T133-T137，不代表当前源码已经具备 LlamaIndex 实现。

| 扩展点 | 实现方式 |
|--------|---------|
| 新增模型Provider | 继承BaseModelProvider |
| 新增在线文档平台 | 继承OnlineDocAdapter |
| 新增工具 | 继承BaseTool并注册 |
| 新增Skill | 继承BaseSkill |
| 新增执行器 | 继承BaseExecutor |
| 新增性能引擎 | 实现PerfEngine接口 |
| 新增通知渠道 | 继承BaseChannel |
| 新增主动建议触发 | 继承BaseTrigger |
| 新增需求分析能力 | 继承BaseAnalyzer |
| 新增用例评审规则 | 继承BaseReviewRule |
| 新增ROI指标 | 继承BaseMetric |


## 24. 开发路线图

### 🟦 24.0【V5.2 已人工确认】纵向切片架构与联调门禁

```text
领域模型/服务 → REST API与权限 → Vue API模块/状态 → 工作台页面 → 前后端联调 → 用户验收
       同一业务模块内闭环完成 ───────────────────────────────────────┘
```

- 🟦 前端按业务域组织API模块、视图和组件，不建立与后端重复的业务规则；权限与数据真理源仍在Django后端。
- 🟦 后端API响应契约一旦进入页面联调必须显式处理成功、字段校验、401、403、404、409及5xx状态，禁止只实现“理想成功路径”。
- 🟦 页面首先满足真实用户决策：说明当前状态、影响范围、下一步和失败恢复方式，技术字段通过易懂标签或辅助说明呈现。
- 🟦 每个闭环至少包含后端专项测试、前端构建/组件测试、真实本地API联调及关键用户路径验证；仅Mock前端数据不能完成验收。
- 🟦 阶段19页面任务按各自后端依赖前置执行，阶段22补齐原清单遗漏页面；编号不代表集中开发顺序。

> 说明：功能优先级表示目标产品的重要程度，不等同于发布批次。UI、性能和APP测试虽为目标态P0能力，但按交付计划在第二期完成。

### 第一期（MVP，10-12周）

| 周次 | 内容 |
|------|------|
| 第1周 | 项目初始化、虚拟环境、用户认证、权限 |
| 第2周 | 🟦 模型管理前后端闭环、提示词管理前后端闭环 |
| 第3-4周 | LangGraph智能体、对话交互（含智能应答） |
| 第5周 | 测试环境管理 |
| 第6-7周 | 需求分析全链路+用例生成+评审+筛选 |
| 第8周 | 接口测试（含业务联调） |
| 第9周 | AI测试+知识库+检索 |
| 第10周 | 报告与覆盖度前后端闭环、全局交互回归 |
| 第11周 | 通知中心 |
| 第12周 | Git集成+部署 |

### 第二期（2-3个月）

#### RAG 二阶段专项（下一阶段，建议优先于依赖知识模型的智能体能力）

```text
契约/兼容性验证
  → pgvector 数据底座
  → Embedding Provider 与模型路由
  → 异步索引生命周期
  → LlamaIndex 适配
  → pgvector + PostgreSQL FTS 混合检索
  → 重排序/上下文/引用
  → REST API + 知识库工作台
  → LangGraph retrieve_node
  → 评测、观测、安全和发布验收
```

该专项对应任务 T133-T144。T133-T141 先形成可独立使用的知识库 RAG 闭环；T142 依赖统一智能体运行时和主图边界，不能为接入 RAG 而绕过 T107/T039 的历史架构缺口。MR-05 中的知识库模型路由应等待 T135，智能体知识增强应等待 T142；报告生成等不依赖知识检索的功能可按自己的任务继续。

- P0：单一真实 Embedding 模型、审核后索引、pgvector + FTS 混合召回、项目隔离、引用、失败可恢复、知识库工作台。
- P1：reranker、个人化排序、自动知识沉淀、复杂查询改写和更多在线连接器。
- 禁止：为使用 LlamaIndex 而迁移全部业务模型、引入独立向量数据库、同时启用多个主编排器或无评测上线。

- UI测试 + 性能双引擎 + APP测试
- 主动建议 + 多人协作 + 知识审核
- 测试资产沉淀与复用
- 操作级权限与审批流
- 🟧 【V5.1】MCP能力网关与高风险工具HITL确认
- 🟧 【V5.1】LlamaIndex知识检索适配在第一期知识库任务中前置完成，第二期补充高级连接器与评估
- 需求版本与变更追踪
- 测试数据准备与构造
- 用例执行顺序与依赖编排

### 需求分析结果稳定性边界（T155B）

需求分析结果采用“不可变分析记录 + 文档级可比较基线 + 覆盖完整性报告”模型。源文档正文、解析证据、实际模型路由、Prompt 配置标识和 Schema 版本共同生成分析指纹；每次分段运行保留证据范围、完成状态、截断/失败原因和合并结果。分析记录必须将 `complete`、`partial`、`needs_review`、`failed` 与模型调用状态分开表达，合法 JSON 不能绕过覆盖校验。清除当前展示记录时，源文档和最近一次安全分析摘要保留，后续运行根据指纹和计数差异生成可审计比较结果；低覆盖结果不得静默作为完整结果供下游使用。

### 第三期（3-6个月）

- 用例质量度量与持续优化
- 测试效果度量与ROI
- Skill自定义 + CI/CD深度集成
- 多智能体协作 + 高级分析
- 🟧 【V5.1】完成CrewAI、AutoGen与Microsoft Agent Framework技术评估；仅在评估通过后启用一个可选多智能体运行时
