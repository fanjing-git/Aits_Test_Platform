# AI 智能体测试平台开发状态

Updated: 2026-09-14 (Asia/Shanghai)

## 2026-09-14 T147 首个管理员初始化与首次安装闭环（本地与目标部署验收）

- 补漏原因：目标部署数据库保留旧 `admin` 账号，但未交付其密码；`platform_admin` 未被初始化，导致代码部署成功而用户无法登录验收。该问题不是账号重置，而是首个管理员交接流程缺失。
- 实现：新增 `python manage.py bootstrap_platform_admin` 和首次安装 REST/UI。新部署没有管理员时访问 `/login` 自动进入 `/setup`，用户自己设置管理员账号和密码；初始化后入口关闭并返回 409，重复启动不改密码；同名普通账号、非活动账号或不符合密码策略时安全阻断；无密码配置时 Compose 使用 `--allow-unconfigured` 正常启动并开放 `/setup`；不接受命令行密码，不输出密码。
- 并发/持久化：新增 `users.0004_platformbootstrapstate` 单例锁迁移，串行化首次初始化；部署环境变量仍作为无人值守部署兜底，真实密码必须保留在未提交的部署密钥或 `.env.remote` 中。
- 部署模板：远程 Compose 后端启动时执行幂等初始化；`6162c83` 已部署到 `124.222.221.128`，`users.0004_platformbootstrapstate` 已应用，原 PostgreSQL 数据卷保留。
- 影响矩阵：`PlatformBootstrapState`/bootstrap Service → 首次安装 REST、管理命令和 JWT 登录；`BootstrapSetupView.vue`/`bootstrap.js` → `/login` 首次访问跳转和管理员工作台；既有注册、邀请、激活、重置、角色管理 REST 和用户管理页面保持兼容。
- 第一轮专项：首次状态/创建/关闭、真实 JWT 登录并访问管理员接口、重复部署保留原密码、同名普通账号不变、无管理员无密码阻断、无密码配置正常启动、弱密码阻断、旧管理员安全启动 9/9；原 T147 账号邀请/激活/重置/权限专项包含在内。
- 第二轮回归：最终代码状态后端全量 411/411；Django check 通过；迁移检查无变更；compileall 通过；前端 Vite 生产构建通过；本地 5173、8000 和 `/api/health/` 均 HTTP 200；Compose YAML 本地解析通过。由于本机未安装 Docker CLI，未执行本地 `docker compose config`。
- 浏览器链路：清除旧 JWT 后，`platform_admin` 本地登录 HTTP 200，`/api/auth/me/` HTTP 200，工作台显示 `admin`；Network 关键认证请求均 200，Console 0 errors。首次安装页面的业务边界由 REST 专项覆盖；已有管理员状态下 `/setup` 自动关闭。
- 编码复核：本次整改后对已跟踪的用户页面、用户 API 和模型文案源码执行乱码检索，未发现页面级乱码；补正一处历史测试夹具中的乱码样例为“登录”。中文界面验收仍需以目标服务器部署后的浏览器复核为准。
- 目标验收：前端 `8090` 与后端健康接口均 HTTP 200，`/api/auth/bootstrap/status/` 返回 `setup_required=false`；目标浏览器使用 `platform_admin` 登录 200，`/api/auth/me/` 200，工作台和用户权限页显示管理员；直接访问 `/setup` 自动回到工作台，Console 0 errors。目标原有 `admin` 未重置；发现目标已有 `platform_admin` 为 viewer 后，仅按本次明确部署要求提升为 admin，未修改密码；旧前端 dist 保留为 `dist.backup-6162c83`。
- Git/交付：`316e40b` 完成首次安装闭环，`6162c83` 补正最后一处历史测试夹具乱码并更新状态；两次均已推送 `origin/master`。目标未新增项目/智能体测试数据，未执行数据清理或删除。
- 下一步：按门禁停止等待用户确认；后续若要把首次安装页做成新客户部署向导或继续统一历史英文/中文文案，另立任务处理。

## 2026-09-14 T161 官方模型目录与选择器闭环完成

- 任务范围：仅完成 T161；未进入 T160 的目标供应商真实调用、费用验收或全链路最终审查。
- 后端目录契约：模型目录统一返回来源类型、来源地址、版本、更新时间、过期标记、目录状态、账号访问状态、实际调用状态、协议和手工模型入口标记。官方 Provider 优先走实时目录；静态列表明确标记为“官方参考快照”，不代表当前账号清单，过期快照会提示重新同步。
- 手工边界：自定义和本地 Provider 不请求或生成虚假官网模型列表，API 返回 `manual_only`，保留手工模型 ID；Azure 继续保留既有实时目录路径，同时允许部署名称手工输入。
- 连接测试：目录存在仅标记 `listed`，目录成功不再推断实际可调用；实际探测成功才标记 `callable`；鉴权失败、目录未列出、无可靠目录和网络失败分别保留可区分状态与错误码。
- REST/前端：`/api/configs/models/catalog/` 与 `/api/configs/models/discover/` 输出上述状态；模型配置页展示来源、目录/账号/模型/调用状态和更新时间，按协议与声明能力过滤，并保留加载、空目录、过期、错误和手工模型入口反馈。新增页面文案均为中文，无新增乱码文本。
- 变更影响矩阵：`catalog.py` -> 模型目录 REST 与 `ModelConfigView.vue` 选择器；`discover_models` -> 所有供应商目录同步和目录连接测试；`ConnectionTestResult` -> 连接测试 API 与前端结果弹窗；`modelCatalog.js` -> 分页同步元数据；未改变模型配置持久化结构、密钥存储或业务调用签名。旧 `source` 字段保留，新增字段向后兼容。
- 第一轮专项：T161 目录/状态专项、既有模型发现和协议专项 27/27；覆盖参考快照过期、实时目录、分页、能力标识、自定义/本地手工边界、目录成功不等于实际调用、401/403、无效响应和本机网络错误。
- 第二轮全量：后端全量 402/402；Django check 通过；`makemigrations --check --dry-run` 无变更；Python compileall 通过；前端 Vite 生产构建通过；`git diff --check` 无 whitespace 错误，仅有既有 CRLF/LF 提示。
- 真实本地联调：5173/8000 返回 200；未认证目录接口返回 401；管理员真实 API 返回 10 个 Provider（7 个参考快照、3 个手工入口）；自定义 Provider discover 返回 200、`source_kind=manual_only`、`directory_state=manual_only`、模型数 0。Playwright 页面刷新后模型配置、目录、路由、诊断请求均 200，Console 0 错误；页面切换自定义 Provider 显示中文手工入口并未产生持久化数据。
- 环境/依赖：无新增迁移、第三方依赖、环境变量、密钥或远程变更；未推送 Git；既有开发库中的 2 个模型配置未删除，项目/智能体验收测试数据保持已清理状态。
- 遗留问题：静态参考快照仍需按供应商官方变更维护；实时目录成功只证明目录接口可访问，实际调用仍须显式执行 inference 测试；T145/T146 台账历史状态仍需在 T160 全链路审查时统一核对。
- 下一任务：T160 全链路兼容性与真实验收；进入前必须处理 T145/T146 状态一致性并取得目标供应商一次短调用的明确授权；本任务完成后按门禁停止等待确认。

## 2026-09-14 T160 全链路兼容性审计进行中

- 本轮范围：仅执行 T160 的依赖审计、全量回归、迁移/构建检查和本地闭环复核；未修改业务代码，未发送供应商真实模型请求。
- 依赖审计：T161 已完成；T145 记录了目标服务器的无 Key 网络响应证据，但缺少 Django 与 Celery Worker 运行身份的独立当前证据；T146 的安全校验、错误分层和本地 Mock/REST/前端证据已完成，但真实短调用仍未执行。因此 T145/T146 的任务表状态和历史记录存在口径差异，暂不能将 T160 标记通过。
- 回归证据：后端全量 402/402；Django check 通过；`makemigrations --check --dry-run` 无变更；Python compileall 通过；前端 Vite 生产构建通过；本地 5173、8000 和 `/api/health/` 均 HTTP 200。
- 本地业务证据：管理员目录接口返回 10 个 Provider；自定义 Provider 返回 `manual_only` 且模型数为 0；模型配置页关键接口均 200，刷新后 Console 0 错误；项目与智能体测试数据已清理。
- 未完成门禁：未取得“对指定供应商、指定模型执行一次无业务数据、无自动重试的短调用”明确授权，未验证供应商实际调用成功/失败、费用提示和目标运行身份的最终闭环。
- 下一步：收到明确供应商与模型授权后，只执行一次最小短调用并记录脱敏结果；若未授权，T160 保持进行中，不将目录 200 或连接测试通过误判为全链路通过。

## 2026-09-14 T160 真实供应商短调用完成，最终审查仍待依赖核准

- 授权范围：用户明确授权使用已保存的 DeepSeek `deepseek-chat` 配置执行一次不含业务数据、最多 16 tokens、无自动重试的短调用；未执行第二次供应商请求。
- 真实结果：管理员通过本地 REST `POST /api/configs/models/7/test-connection/` 以 `mode=inference` 发起调用，HTTP 200，`ok=true`，`inference_verified=true`，`stage=inference`，`account_access_state=verified`，`model_state=callable`，`model_call_state=callable`，脱敏耗时约 1718 ms；未记录 Key、请求体或响应正文。
- 链路证据：本地 5173/8000/健康检查、后端 402/402、迁移/compileall/Django check、前端构建和浏览器关键接口/Console 复核均已通过；项目与智能体测试数据保持清理。
- 变更影响矩阵：本次仅更新本状态记录，真实调用经过既有 `ModelConfigViewSet.test_connection` → `ProviderConnectionTester` → `inference_probe` → DeepSeek OpenAI-compatible transport；未改变模型配置、业务数据或调用代码。
- 最终状态：T160 的供应商短调用门禁已满足，但 T145/T146 仍存在任务表未勾选、目标服务器 Django/Celery 运行身份缺少独立当前证据和历史记录口径不一致的问题。依据“所有受影响链路必须验证”的契约，T160 暂不标记为验收通过，远程部署继续冻结。
- 当前本机运行身份证据：8000 由 `python.exe` 进程监听，Windows 所有者为 `B-03-01\\ZhuanZ`；5173 由 Vite 监听；开发配置使用 `CELERY_TASK_ALWAYS_EAGER=True`，未发现独立 Celery Worker/Beat 监听进程。该证据仅证明本地开发态，不替代目标部署环境证据。
- 后续整改：补齐 T145/T146 的目标运行身份与安全/网络证据，统一任务台账后，再进行一次不涉及供应商调用的最终文档审查。

## 2026-09-14 T159 Model call observability and frontend diagnostics completed

- Scope: completed T159 only. The shared routed and legacy fallback model managers now persist one bounded, credential-free diagnostic per attempt; T160 full compatibility review and authorized provider acceptance remain separate.
- Backend: added `ModelCallRecord` and migration `configs.0007_modelcallrecord`; fields cover request ID, feature/task, route source, capability, fallback flag, status, failure stage, stable error code, retryability, duration, cost reporting state/hint, and bounded trace. No prompt, response, API key, authorization header, proxy credential, or request body is stored.
- Runtime: instrumented `ModelManager.execute_routed` and `execute_with_fallback`. Primary and explicitly allowed fallback attempts share one request ID; route/capability blocks are recorded before any provider call; diagnostic persistence failures do not break the business call.
- REST/frontend: added admin-only `GET /api/configs/models/call-records/` with safe filters and a model configuration workbench panel showing request/feature, effective route, outcome, timing/cost state, retry boundary, and recent trace. Empty, service-failure, and retry states are rendered explicitly.
- Impact matrix: `ModelManager` -> requirement analysis, case generation/review, agent execution, and future report callers; `ModelCallRecord` -> configs migration/admin diagnostics API; diagnostics API -> `ModelConfigView.vue` and `modelCalls.js`; existing `ModelUsageRecord` aggregation remains unchanged. Existing manager signatures remain compatible; `request_id` is optional.
- First round: T159/configs routing and legacy fallback focused tests 28/28, including success, explicit fallback, blocked route, sensitive-field exclusion, 401, and 403.
- Second round: backend full regression 396/396; Django check passed; `makemigrations --check --dry-run` reported no changes; compileall passed; frontend Vite production build passed; `git diff --check` reported no whitespace errors (only existing CRLF/LF notices).
- Real local integration: migration `configs.0007_modelcallrecord` applied; 5173/8000 returned HTTP 200; authenticated admin browser loaded the diagnostics panel; `GET /api/configs/models/call-records/?limit=30` returned 200 and rendered both a real local `ModelManager.execute_with_fallback` diagnostic and a completed sanitized acceptance fixture with route, duration, cost state, and trace; after fresh login, the browser Console had 0 errors and model APIs were all 200.
- Environment/dependencies: one database migration added; no new package, environment variable, credential, or remote change; no Git push.
- Remaining: T160 must perform the full compatibility/acceptance review; cost totals still depend on future provider usage reports and are deliberately shown as not reported when unavailable.
- Next task: T160 full-chain compatibility and real acceptance; stop here and wait for confirmation.

## 2026-09-14 T158 Embedding/RAG 能力边界与接入门禁完成

- 任务范围：仅完成 T158 的能力边界和接入门禁；未实现供应商 Embedding Provider、pgvector、混合检索、Rerank 或完整 RAG 工作台，这些仍属于阶段24 T133-T144。
- 后端：新增 `EmbeddingPolicyService`，将 `knowledge_model` 路由、Embedding 能力、显式执行模式和稳定错误码统一起来；生产默认 provider 路径在未配置、能力不匹配或 Provider 未接入时安全阻断；`HashVectorizer` 仅允许显式 `offline_test` 且仅在 DEBUG 环境使用，并写入模式、模型和维度元数据。
- REST：新增 `GET /api/knowledge-search/policy/` 能力诊断；文档索引和知识检索使用 DRF 请求 Serializer，要求显式 provider/offline_test 模式；未配置或能力不匹配返回可行动的 `code` 和脱敏策略信息。
- 智能体链路：没有项目知识库引用时跳过检索，避免无意义 Embedding 调用；配置 `knowledge_search` 工具但没有知识库或 Provider 不可用时明确失败，不绕过项目边界。
- 前端：知识库工作台加载并展示 Embedding 能力状态、模型类型不匹配和运行时未接入提示；索引/检索显式请求 provider 模式，保留服务失败和重试反馈。
- 变更影响矩阵：`EmbeddingPolicyService` → 知识库索引/检索 REST、智能体规划节点、`knowledge_search` 工具；知识请求 Serializer → 文档索引和搜索接口；Embedding policy API → `KnowledgeView.vue` 状态提示；旧 `HashVectorizer` 直接 Python 调用 → 保留为测试/迁移兼容路径。覆盖正常诊断、无路由、能力不匹配、显式离线、401、403、空知识库和旧检索调用方。
- 第一轮专项：T158 与受影响知识/智能体调用方专项 28/28；覆盖生产门禁、显式离线模式、项目隔离、错误边界、401/403。
- 第二轮全量：后端全量 392/392；Django check 通过；`makemigrations --check --dry-run` 无变更；Python compileall 通过；前端 Vite 生产构建通过；`git diff --check` 无 whitespace 错误，仅保留既有 CRLF/LF 提示。
- 真实本地联调：前端/后端 5173/8000 返回 200；浏览器知识库页显示 Embedding 门禁提示；真实 `GET /api/knowledge-search/policy/` 返回 200；真实 provider 检索在当前 chat 模型路由下返回 400 和 `model_capability_mismatch`；新浏览器页 Console 错误 0。
- 环境/依赖：无新增数据库迁移、第三方依赖、环境变量、密钥或远程变更；未推送 Git。旧 T027 API 测试改为显式 `offline_test`，避免把历史兼容测试误当作生产 RAG。
- 遗留边界：实际 Embedding Provider、固定维度/版本索引、pgvector/FTS 混合检索、引用和成本治理仍需阶段24 T133-T144；当前知识库页面会明确阻断，不能把本地 HashVectorizer 结果标记为生产 RAG。
- 下一任务：T159 模型调用可观测性与前端反馈；已完成并记录在本文件顶部。

## 2026-09-14 T157 智能体模型执行闭环与真实浏览器验收完成

- 任务范围：仅完成 T157；在既有 AgentGraph 确定性路径旁增加项目级受控模型执行路径，未进入 T158/T159/T160。浏览器已完成一次明确授权的真实短调用，模型调用和结构化结果返回成功。
- 后端：新增 `AgentExecution` 持久化审计记录、受控 Celery 任务、模型路由与结构化 JSON 调用、超时边界、暂停/取消/恢复控制和可重试错误；只允许显式配置且平台白名单内的 `knowledge_search`，所有其他模型工具请求直接阻断；知识库 ID 先按项目和启用状态过滤。
- REST：新增 `POST /api/agents/:id/execute/`、`/api/agent-executions/` 查询以及 pause/cancel/resume 控制动作；项目成员可执行，viewer 只能读取，项目外用户不可发现，匿名请求返回 401。
- 前端：项目智能体卡片新增 Execute 入口和执行状态面板，展示状态、阶段、脱敏路由、结果、失败重试提示和审计轨迹；加载、空数据、字段错误、401/403、服务失败均保留反馈路径。
- 变更影响矩阵：`AgentGraph.invoke` → 既有确定性图测试与新模型执行分支；`AgentExecutionService` → Celery 任务、Agent execute REST、execution 控制 REST；`AgentExecution` → serializer、项目隔离查询和工作台面板；`agents.js` → `ProjectAgentView.vue` 执行入口。已验证旧图路径、执行成功/失败/工具阻断/暂停恢复、权限边界、迁移和构建。
- 第一轮专项：T157 专项与旧 AgentGraph 回归 7/7；Django check、迁移生成/一致性、Python compileall 通过。
- 第二轮全量：后端 `manage.py test` 386/386；本地迁移 `agents.0002_agentexecution` 已应用；前端 Vite 生产构建通过；`git diff --check` 仅有既有 CRLF/LF 提示，无 whitespace 错误。
- 本地联调：`http://127.0.0.1:8000/`、`/api/health/`、`http://127.0.0.1:5173/` 返回 200；重新登录后项目/API 请求均 200，创建启用智能体返回 201，Execute 入口和弹窗可见，空输入显示字段错误；带 `interrupt_signal=pause` 的本地预检返回 201，重新打开弹窗显示 Paused 和 Audit trace；当前浏览器控制台无阻断性错误。真实短请求返回 `Completed`，`phase=completed`，Audit trace 包含 `model_call=completed` 和 `graph=completed`，结果区域返回结构化 JSON。
- 环境/依赖：新增 1 个 Django 迁移；未新增第三方依赖、环境变量、密钥或远程变更；未推送 Git。新增后端 T157 文件源码无乱码字符。
- 遗留边界：本地真实模型短调用已验收通过；本地验收产生的 T157 测试智能体和暂停/失败/成功记录保留在当前开发库；阶段 27 任务表中 T155B/T156 的历史状态标记与归档记录仍存在不一致，未在本任务顺带修改。
- 下一任务：T158 Embedding/RAG 能力边界与接入门禁；本任务只处理能力标识、维度/版本校验、敏感数据策略和接入门禁，不扩展为完整 RAG 二期实现。

## 2026-09-10 今日归档与下次续接入口

- T155B 补缺整改已完成并通过专项 28/28、后端全量 374/374、前端测试 12/12、前端构建和本地服务检查。
- 当前未完成项：千问真实调用受本机网络限制，`dashscope.aliyuncs.com:443` TCP 连接失败，返回 `tcp_blocked`；这不是需求分析 JSON、分段或 8192 限制问题。
- 下次续接顺序：先确认后端 Python 进程的外网放行或 `HTTPS_PROXY` 配置，再进行一次短调用验证；未解决网络前不要反复点击深度分析，也不要进入 T157。
- 本次未新增迁移、依赖、环境变量或远程变更；未推送 Git。工作区保留既有未提交变更。

## 2026-09-10 T155B 补缺整改：清除后再次分析失败可诊断与可恢复

- 任务范围：修复首次分析成功、清除记录后再次分析在第 0 个分段失败时只显示 `model_error`、刷新后没有失败轨迹的问题；不执行真实供应商调用。
- 后端：模型 fallback 异常保留最后一次底层异常；需求分析透传真实错误码和结构化分段 trace；即使完成 0 个分段，也持久化 `failed` 分析记录，不生成伪造的确定性结果；失败记录不会成为下一次成功分析的数量基线。
- 前端：刷新后显示结构化分析失败、已完成分段数和错误码；保留手动重试与刷新路径。清除接口继续保留原文和解析证据，分析可直接使用清除前的解析快照。
- 变更影响矩阵：`ModelFallbackExhausted` → 需求分析/用例生成共享模型调用；`RequirementModelAdapter` → 结构化错误码与 trace；`analyzer.py` → 失败分析持久化、基线比较和需求 REST；`RequirementAnalysisView.vue` → 失败状态展示。已覆盖正常结果、0 段失败、部分完成、重试恢复、清除后原文/证据保留、旧 fallback 和权限边界。
- 第一轮专项：T155B/T155/T155 模型选择/模型管理专项 28/28；Python 编译、`git diff --check` 通过。
- 第二轮全量：后端 `apps` 全量 374/374；Django system check、迁移一致性检查通过；前端 Node 测试 12/12；Vite 生产构建通过；本地前后端 HTTP 200。
- 真实联调边界：仅检查本地页面和接口可达性，没有点击深度分析，没有发送新的供应商请求，未产生新增费用。
- 环境/依赖：无新增迁移、第三方依赖、环境变量、密钥或远程变更；未推送 Git。
- 遗留边界：千问供应商本次失败的真实底层原因仍需用户授权 T160 的一次短调用后才能最终确认；当前系统已能保留并展示实际返回错误码和分段轨迹。
- 下一任务：T157“智能体真实模型执行闭环”；本补缺完成后按门禁停止等待用户验收。

## 2026-09-10 T156 用例生成与评审纵向闭环完成

- 任务范围：完成五轮用例生成、五轮评审、自动化筛选的状态闭环；真实供应商调用仍按 T160 门禁冻结。
- 后端：生成与评审逐轮记录 `status`、模型状态、错误码、结构化分段轨迹和安全路由证据；模型中途失败时保留失败轮次与部分结果，严格路径不再用确定性结果伪装 `model_verified`；无可用模型时明确标记确定性基线，显式降级标记 `deterministic_fallback`。
- 共享链路：`RequirementModelAdapter` 将实际执行配置写入脱敏 `model_route`；路由/能力诊断统一转换为 JSON 标量，修复首次响应与刷新后响应不一致的幂等问题。
- 前端：用例生成工作台增加长任务等待状态、已等待秒数、当前操作重试入口、每轮执行证据、模型/错误码展示和失败记录恢复提示；保留加载、空数据、字段错误、401/403、服务失败与刷新恢复路径。
- 变更影响矩阵：`RequirementModelAdapter` → 需求分析/用例生成/评审结构化调用；`generator.py` → 生成 REST → `CaseGenerationView.vue`；`reviewer.py` → 评审 REST → 同一工作台；路由 JSON 诊断 → 模型选项接口与历史记录幂等读取。覆盖正常、无模型、模型失败、部分结果、旧记录、权限和重试。
- 第一轮专项：T156 新增专项与 T046/T047/T095/T155B 受影响回归共 28/28；前端 Node 测试 12/12。
- 第二轮全量：后端 `apps` 全量 369/369；Django system check、迁移一致性、Python 编译、`git diff --check` 通过；前端 Vite 生产构建通过。
- 真实本地联调：8000/5173 均可访问；重新认证后的用例生成页项目、需求文档、生成记录、生成/评审模型选项接口均 HTTP 200，模型选项返回实际生效模型与路由来源；浏览器唯一首轮认证 401 自动刷新后恢复 200，未触发生成/评审按钮，未发起真实供应商调用。
- 环境/依赖：无新增迁移、第三方依赖、环境变量、密钥或远程变更；未推送 Git。
- 遗留边界：真实供应商成功/失败、费用、超时和长输出仍需 T160 明确授权；当前工作台历史记录来自此前失败尝试，未借本次验证伪造成功结果。
- 下一任务：T157“智能体真实模型执行闭环”；按任务门禁停止等待用户验收，不进入 T157 以外任务。

## 2026-09-10 T155B 需求分析结果可重复性与覆盖完整性整改完成

- 任务范围：完成 T155B，解决清除记录后重新分析数量大幅波动却仍被显示为成功的问题；已同步 `PRD_V5.0.md` 第 21.8 节、`TASKS_V5.0.md` 阶段27任务依赖、`TECH_ARCH_V5.0.md` 稳定性边界和 `LLM_CALL_CHAIN_REMEDIATION_PLAN.md`。
- 后端数据与服务：`RequirementAnalysis` 新增源指纹、分析指纹和 `complete/partial/needs_review/failed` 完整性状态；`RequirementDocument` 新增安全分析基线；清除记录时保留最近一次不含原文的基线摘要，下一次分析可跨清除比较。
- 覆盖校验：新增 `stability.py`，按解析证据 ID 统计已覆盖、未覆盖和未提供引用的分析项；分段轨迹记录证据 ID；同一基线下任一结果集合下降 20% 及以上会生成差异摘要并标记待复核，不能静默视为等价完整结果。
- 下游门禁：模型验证结果为 `partial` 或 `needs_review` 时，禁止进入用例生成；确定性证据基线仍按既有安全降级路径运行，并继续显示未进行真实模型验证的提示。
- 前端闭环：需求分析页展示完整性状态、证据覆盖、数量下降提示和清除后保留基线说明；旧分析记录若没有新覆盖报告，也会根据持久化状态显示“分析结果待复核”。
- 变更影响矩阵：`RequirementAnalysis/RequirementDocument` 字段 → 迁移 `0005_requirementanalysis_quality_and_baseline` → `analyzer.py`/`stability.py` → 需求分析 Serializer/REST → `RequirementAnalysisView.vue`；共享分段轨迹影响 `structured_runtime.py`/`RequirementModelAdapter`；质量门禁影响 `case_generation/generator.py`。覆盖历史分析读取、清除幂等、用例生成入口、模型路由和旧记录默认值。
- 第一轮专项：T155B 稳定性与覆盖专项、T155/T155A/清除记录调用方回归共 14/14 通过；需求分析与用例生成 app 回归 83/83 通过。
- 第二轮全量：后端全量 372/372；Django system check 通过；`makemigrations --check --dry-run` 无变更；`compileall` 通过；前端 Node 测试 12/12；Vite 生产构建通过；`git diff --check` 通过。
- 真实本地联调：应用本地 `requirement_analysis.0005` 迁移后，需求工作台加载、项目、需求文档、模型选项接口均 HTTP 200；页面展示“分析结果待复核”和已有分段状态；最终干净重载 Console 0 错误、0 警告。首次联调出现的未应用迁移 500 已修复并复验；未发起新的真实供应商模型调用。
- 环境/依赖：新增 1 个 Django 数据库迁移；未新增第三方依赖、环境变量、密钥或远程变更；本地开发数据库已应用迁移。
- 遗留边界：模型仍可能生成语义不同但结构合法的候选结果；T155B 已阻止低覆盖结果被当作完整结果，但真实供应商重复运行的最终语义一致性、成本和网络表现仍需 T160 明确授权后验收。
- 下一任务：T156“用例生成与评审纵向闭环”；按任务门禁停在 T155B 用户验收，不推送远程 Git。

## 2026-09-10 T155 深度分析等待状态补充与结果稳定性审计

- 等待状态：需求分析页增加处理中提示、已等待时长和 30 秒后的长任务说明；当前后端为同步分段调用，尚未返回前不能显示真实的 `x/y` 分段进度，避免伪造进度。
- 已确认问题：清除记录后再次分析会重新调用模型。`plan_structured_segments` 按证据分组并重复携带正文，`execute_structured_segments` 逐段调用，`merge_structured_payloads` 只做结构合并/精确去重；没有稳定结果缓存、随机种子、固定实体清单或完整覆盖校验。`temperature=0` 只能降低随机性，不能保证供应商跨次输出一致。
- 影响：同一需求可能出现模块、功能点、联合场景和测试点数量明显波动；合法 JSON 不等于完整抽取，当前结果不能把较少数量直接视为准确覆盖。
- 未关闭项：需单独设计“结果可重复性与覆盖完整性”整改，至少增加稳定输入指纹/可选结果复用、证据覆盖清单、遗漏检测、截断/不完整标记和重复运行对比；在该问题解决前，不将不同分析次数的数量视为可比基准。
- 当前验证：前端 Vite 构建通过，Node 测试 12/12；未发起新的供应商模型调用。等待状态改动完成后暂停，不进入新的业务任务。

## 2026-09-10 需求分析清除记录功能完成

- 功能范围：新增“清除分析记录”入口和二次确认；只删除当前需求文档的深度分析历史及视觉分析报告，保留需求原文、文件、解析证据和已有用例生成记录。
- 后端闭环：新增事务服务 `RequirementAnalysisRecordService.clear_records` 与 `POST /api/requirement-documents/:id/clear-analysis/`；清除后文档回到“已上传”状态，重复清除幂等，查看者/无权限用户返回 403。
- 前端闭环：需求分析工作台显示清除按钮、保留范围提示、成功反馈、失败反馈和空记录禁用状态；不替用户点击现有文档的清除按钮。
- 变更影响矩阵：需求分析文档 → 清除记录 Service → REST action → `RequirementAnalysisView.vue`；用例生成历史只读保留，原文解析和模型路由不受影响。
- 第一轮专项：清除成功、原文/解析证据保留、视觉报告清空、用例记录保留、重复清除幂等、查看者 403，共 17/17 通过。
- 第二轮全量：后端 `apps` 全量 361/361；Django check、迁移检查、compileall、前端 Node 测试 12/12、Vite 构建和 `git diff --check` 通过。
- 真实本地联调：临时文档页面点击清除并确认，REST HTTP 200，页面显示“分析记录已清除（1 条）”；临时文档随后已删除；新浏览器页关键 API 均 HTTP 200，Console 错误 0、警告 0。
- 下一任务：T156“用例生成与评审闭环”；本功能完成后按门禁停止等待用户验收，不推送远程 Git。

## 2026-09-10 T155 深度分析前端超时修复

- 根因：需求分析采用 T155A 分段结构化调用；当前“恐龙”文档实际执行了 9 个分段。前端 Axios 全局超时仅 10 秒，后端仍在正常处理时浏览器已先中断请求，页面因此只显示“操作失败，请重试”，并掩盖了后端最终保存的结果。
- 修复：需求深度分析和截图视觉分析使用独立的 10 分钟请求超时，不再沿用普通查询的 10 秒超时；若仍达到等待上限，页面明确提示后端可能仍在处理，并引导刷新查看已保存的部分结果。
- 真实本地复核：刷新需求工作台后，当前文档显示 `deepseek · requirement_analysis · 已验证`，结构化分段显示 `9 / 9` 完成；`auth/me`、项目、需求文档、模型选项均 HTTP 200，Console 错误 0、警告 0。
- 影响范围：`frontend/src/api/requirements.js` 的深度/截图调用、`frontend/src/api/caseGeneration.js` 的用例生成/评审调用 → 对应工作台错误反馈；后端路由、数据结构、供应商 Key 和迁移未改变。
- 验证：后端 T155/T155A/T043/T154 相关专项 20/20；后端 `apps` 全量 358/358；前端 Node 测试 12/12；Vite 生产构建通过；`git diff --check` 通过。

## 2026-09-10 T155 需求分析与视觉调用闭环完成

- 实现内容：需求深度分析继续使用 T154 实际生效路由和 T155A 共享结构化分段运行时；覆盖模型验证、部分完成、失败和确定性基线状态，记录安全的模型路由、调用阶段、错误码、分段轨迹和可重试边界。联合功能识别明确标记为确定性证据方法，不伪装成模型调用。
- 视觉闭环：新增视觉模型结构化输出校验，要求元素、文本块、区域和测试点保持唯一 ID 与证据引用；截图分析优先走视觉模型，未配置视觉模型时只返回明确的 OCR 基线；截图报告持久化到 `RequirementDocument.visual_analysis_report`，刷新后仍可查看。
- REST 状态：模型调用失败返回安全错误码、`failed/partial`、`retryable`、文档状态和已保存的部分分析；视觉失败同样保留失败报告。新增迁移 `requirement_analysis.0004_requirementdocument_visual_analysis_report`，未新增第三方依赖或环境变量。
- 前端闭环：需求分析页恢复持久化视觉报告，显示模型/基线结果、置信度、错误码和调用阶段；失败时提供当前操作重试和页面刷新；保留加载、空数据、权限、服务错误和能力不匹配提示。
- 变更影响矩阵：`RequirementAnalysisError`/`RequirementModelAdapter`/`analyze_requirement_document` → 需求分析 REST `analyze` → `RequirementAnalysisView.vue`；`analyze_visual`/视觉报告字段 → `screenshot-analysis` REST → 截图分析入口和刷新状态；`identify_document_linkages` → 联合识别 REST/分析覆盖报告。调用方覆盖旧的确定性分析、T155A 分段运行时、模型路由、项目权限、历史分析记录和前端认证。
- 第一轮专项：T155 需求分析/视觉 REST、模型结构化校验、失败部分持久化、路由信息、截图文件边界及 T155A/T043/T049/T094/MR-03 受影响回归共 31/31 通过。
- 第二轮全量：后端 `apps` 全量 358/358；Django system check 通过；`makemigrations --check --dry-run` 无变更；`compileall` 通过；`git diff --check` 通过；前端 Vite 生产构建通过。
- 真实本地联调：重新认证 `platform_admin` 后，需求分析工作台加载成功；干净浏览器页的 `auth/me`、项目、需求文档、模型选项请求均 HTTP 200，Console 错误 0、警告 0。另以临时 OCR 文档验证截图入口：当前全局文本模型被明确阻断为 `model_capability_mismatch`（400），页面显示重试入口且未发起供应商请求；临时数据已通过页面删除。未点击真实模型分析/视觉推理按钮，避免在 T160 授权前产生供应商费用。
- 边界证据：专项测试覆盖正常模型结果、无效证据、供应商失败、部分结果、无视觉文件、项目权限和匿名 401；现有回归覆盖空输入、字段错误、403、跨项目隔离和 OCR 失败。真实供应商长输出、费用和目标环境网络仍属于 T160 授权验收。
- 下一任务：T156“用例生成与评审闭环”；按门禁停止等待用户确认，不进入 T157/T161，不推送远程 Git。

## 2026-09-10 T155A 长输入与长结构化结果分段生成闭环完成

- 实现内容：新增 `backend/core/llm/structured_runtime.py`，提供预算分段、证据/段落边界切分、结构化截断后的受控拆段、最大分段上限、确定性合并、ID 冲突修复、已知引用重写和段级轨迹；`structured_max_tokens=8192` 仍只是单段上限，不再被当作任意长度保证。
- 调用方接入：`RequirementModelAdapter` 统一接入共享运行时；需求分析按证据/正文分段；用例生成按功能点分段；用例评审按用例分段；现有无真实结构化模型节点的报告/智能体不伪造接入，保留给后续 T156/T157 的真实业务闭环。
- 失败恢复：输出长度截断会拆分当前段而不是无限重试；中途服务失败/解析失败会保留已完成段、部分需求分析、已有用例或评审问题，并标记 `model_partial`/`partial`，前端明确提示不能视为完整模型验证；原生 Anthropic/Google 长度结束原因已统一归一化。
- REST/前端闭环：复用现有需求分析和用例生成 REST 的 JSON 报告字段返回段状态与轨迹；需求分析页、用例生成页增加完整合并/部分完成提示。未新增数据库表、迁移、第三方依赖或环境变量。
- 变更影响矩阵：`StructuredBatchExecutor` 等价共享运行时 → `RequirementModelAdapter` → 需求分析/用例生成/用例评审 → 既有 REST Serializer/工作台；`parse_openai_json_response`/原生协议归一化 → OpenAI-compatible、Anthropic、Google 结构化调用。覆盖正常、空数据、字段错误、输出截断、无效 JSON、服务失败、旧调用方、ID 冲突、引用重写和部分结果持久化。
- 第一轮专项：T155A 共享运行时、适配器和历史调用方共 40/40；补充原生协议长度原因及段级合并后专项 31/31 通过。
- 第二轮全量：后端 `apps` 全量 352/352；Django system check 通过；`makemigrations --check --dry-run` 无变更；`compileall` 通过；`git diff --check` 通过；前端 Vite 生产构建通过。
- 真实本地联调：重新登录 `platform_admin` 后，需求分析页面的 `auth/me`、项目、需求文档、模型选项请求均 HTTP 200；用例生成页面的项目、需求文档、生成记录、生成/评审模型选项请求均 HTTP 200；两页最终浏览器 Console 错误 0，未触发真实供应商推理调用。
- 遗留边界：当前未授权新的真实 DeepSeek/其他供应商业务调用；供应商费用、真实长输出和目标环境网络仍按 T160 授权验收。T155A 完成的是共享 Mock/本地链路能力，不宣称 T155/T156/T157 已完成。
- 下一任务：T155“需求分析与视觉调用闭环”；按门禁停止等待用户确认，不进入 T156/T161，不推送远程 Git。

## 2026-09-10 T155A 长输入与长结构化结果分段生成需求立项

- 立项原因：T155 将结构化输出上限从 2048 提高到 8192 并增加截断诊断，只能降低短请求失败率；超过单次预算的需求、测试用例、评审和报告仍可能截断，因此问题属于共享模型调用运行时，不是需求分析页面独有缺陷。本节为 T155A 的历史立项记录，当前完成情况以上方完成记录为准。
- 文档同步：新增 `PRD_V5.0.md` 第 21.7 节；新增 `TECH_ARCH_V5.0.md` 第 22.6 节；任务台账新增补充任务 T155A；同步 `LLM_CALL_CHAIN_REMEDIATION_PLAN.md`、`CONTRACT_ENFORCEMENT.md` 和本状态记录。
- 任务边界：T155A 只做预算规划、稳定边界分段、受控续接/截断、幂等执行、结构化合并、部分完成/可恢复失败状态及共享调用方接入；覆盖需求分析、用例生成/评审、报告和智能体结构化输出。立项时尚未开始编码，后续已由上方完成记录闭环。
- 变更影响矩阵：共享结构化运行时 → 需求分析、用例生成、五轮评审、报告、智能体 → REST 状态/重试接口 → 对应前端工作台和审计/费用反馈；必须覆盖正常、空数据、字段错误、401、403、超时、服务失败、输出截断、旧数据/旧接口、取消/恢复和幂等重试。
- 验证记录：立项时仅修改需求、架构、任务、契约和状态文档，未新增代码测试；后续 T155A 的专项、全量、构建和浏览器联调证据见上方完成记录。
- 下一步与门禁：立项时按新依赖先执行 T155A；该任务现已完成，下一任务为 T155。T155A 完成前不进入 T156，也不把 T155 的局部修复宣称为长内容全链路完成；不执行 T161 或 T160 的真实供应商调用。

## 2026-09-10 T155 需求分析 JSON 响应与测试方式状态修复（本次范围）

- 结构化响应修复：`configs.services.parse_openai_json_response` 现在安全移除 DeepSeek 常见的 `<think>` 片段和 Markdown JSON 包裹，并可从带简短前后说明的响应中恢复首个 JSON 对象；恢复后仍由需求分析适配器执行完整字段、唯一 ID、证据引用和业务契约校验，普通文本、数组和无法解析的内容仍失败。
- 截断诊断补充：需求分析结构化输出默认上限由 2048 提高到 8192，可通过 `structured_max_tokens` 或既有 `max_tokens` 参数覆盖；识别供应商 `finish_reason=length/max_tokens` 后返回明确的“模型输出达到长度上限”错误，避免误导为 Key 或路由故障。
- 测试方式修复：`ModelConfigView.vue` 按模型保存最近选择的 `catalog`/`inference` 测试方式到浏览器本地存储；选择实际调用测试后关闭并重新打开同一模型，仍恢复“所选模型实际调用（可能产生少量费用）”，存储失败不会阻断测试。
- 变更影响矩阵：`parse_openai_json_response` → OpenAI-compatible 结构化运行时 → 需求分析、用例生成/评审的 JSON 适配器；`testMode`/测试连接入口 → `testModelConnection` → 模型配置页面弹窗。密钥、路由、供应商协议、模型配置数据库字段和连接测试 API 未改变。
- 链路测试证据：前端选择实际调用模式、关闭弹窗、再次打开同一 DeepSeek 模型后模式保持；无授权 API 探针继续返回 401；管理员页面配置接口 200；最终浏览器 Console 错误 0。
- 第一轮专项：T155 结构化响应测试、T152/T153 协议回归和需求分析调用方共 21/21 通过，覆盖 `<think>`、Markdown fence、前后说明、后缀文本、非 JSON、JSON 数组和长度截断边界。
- 第二轮全量：后端全量 354/354；Django system check 通过；`makemigrations --check --dry-run` 无变更；`compileall` 通过；前端 Vite 生产构建通过；8000/5173 健康检查均 200。
- 遗留边界：本轮未发起新的真实 DeepSeek 计费调用；供应商实时输出仍需在 T160 授权验收中验证。T155 中视觉真实调用闭环尚未因本次两个问题而提前扩展，下一步仍停留在 T155 范围内；不进入 T156、T161。

## 2026-09-10 T154 统一路由解析与能力预检完成

- 统一模型路由结果：`configs.routing` 现在返回安全的候选模型、来源（operation/feature/global/legacy/backup）、能力契约、是否允许备用和明确失败原因；显式路由通过 `validate_model_capability` 做能力预检，不读取或返回密钥。
- 业务调用链收敛：需求分析、用例生成、用例评审和真实 `ModelManager` 均按临时选择→功能路由→全局路由→兼容的 legacy 默认顺序解析；移除“任意启用模型即可用”的业务判断。智能体本轮仅将 options 接口接入同一预检，真实模型执行留在 T157。
- REST/前端闭环：路由矩阵、需求分析模型选项、用例生成/评审模型选项和智能体 options 返回统一 `route` 诊断；现有模型配置工作台、需求分析页和用例生成页继续显示当前生效模型/来源及能力不匹配错误。
- 变更影响矩阵：`ModelRouteResolver`/`ModelManager.execute_routed` → 需求分析适配器与 analyzer、用例生成/评审 → 对应 REST model-options 和路由矩阵 → `RequirementAnalysisView.vue`、`CaseGenerationView.vue`、`ModelConfigView.vue`；旧的显式备用策略、权限、密钥加密、provider 协议适配和确定性基线未被绕过。新增的 agent options 只做能力筛选与诊断，不改变 T157 前的确定性 AgentGraph。
- 第一轮专项：T154 路由/能力/显式备用专项及受影响调用方回归 203/203；覆盖正常路由、空路由、显式模型、能力不匹配、显式跨供应商备用、调用失败和旧测试夹具兼容。初次回归发现 4 个旧夹具依赖“任意活动模型”，已改为显式功能路由后复测通过。
- 第二轮全量：后端全量 349/349；Django system check 通过；`makemigrations --check --dry-run` 显示 No changes detected；`compileall` 通过；前端 Vite 生产构建通过。
- 真实本地联调：管理员页面刷新后，路由矩阵与用例模型选项接口均 HTTP 200；响应包含 `route.candidates`、`capability_contract`、`effective_source` 和 `failure_reason`。当前工作台显示文本路由生效为平台全局模型，截图/知识库能力不匹配显示可行动错误。无 Authorization 的本地探针返回 401；刷新后的浏览器页面 Network 关键请求 200，Console 错误 0。
- 链路测试证据：未配置显式业务路由时，活动模型不会被 `ModelManager.execute_routed` 隐式选中；备用模型只有在策略 `allow_fallback=true` 时进入候选；真实模型调用和计费短调用仍留在 T160。未新增依赖、环境变量或数据库迁移，未远程部署、提交或推送 Git。
- T154 完成；下一任务为 T155。按任务门禁暂停，等待决策者确认后继续。

## 2026-09-10 T152 OpenAI-compatible 协议一致性完成

- 统一连接探测与业务结构化调用：Qwen、DeepSeek、OpenAI、Azure、custom/local 的聊天请求共用 payload、鉴权、超时、响应提取和 JSON 解析边界；Qwen 默认关闭 thinking，DeepSeek 默认发送 `thinking.type=disabled`，OpenAI/Azure 使用 `max_completion_tokens`，其余兼容供应商使用 `max_tokens`，结构化调用统一声明 JSON object。
- 增加结构化调用超时配置 `structured_timeout_seconds` 的 1-120 秒边界，默认 30 秒；响应支持标准字符串、multipart 文本和 fenced JSON，错误只返回脱敏的协议/网络/解析原因，不回显密钥或模型内容。
- 变更影响矩阵：`configs.services.openai_compatible_chat` → `inference_probe`（连接测试）和 `requirement_analysis.OpenAICompatibleRuntime`（需求分析结构化调用）→ `ModelConfigViewSet` 测试连接 REST、需求分析服务 → 模型配置页和需求分析调用方；旧配置字段、鉴权头、路由能力筛选、权限边界和非兼容协议入口未跨任务改动。
- 第一轮专项：T152 协议与调用方兼容测试、模型发现回归、需求分析适配器回归共 25/25 通过；覆盖 Qwen/DeepSeek/OpenAI/Azure 请求体、JSON/multipart/fenced 解析、超时上限、图文消息和错误边界。
- 第二轮回归：后端 `apps` 全量 334/334；Django system check 通过；`makemigrations --check --dry-run` 无变更；前端 Vite 生产构建通过；未新增依赖、环境变量或迁移。
- 真实本地联调：管理员重新登录后，`/api/configs/models/`、`/api/configs/models/catalog/`、`/api/configs/routing-policies/matrix/` 均 HTTP 200，返回模型 2 个、路由矩阵 8 行；新浏览器页加载模型配置工作台时 Console 错误 0，Network 中 `auth/me` 与三个配置接口均 200。未执行外部供应商计费短调用，真实供应商短调用留在 T160 验收范围。
- 链路测试证据：匿名请求仍返回 401（本轮一次无 Authorization 的浏览器探针）；带管理员 JWT 的真实页面请求返回 200；测试中既有密钥脱敏、字段错误、网络失败、旧接口和权限边界继续通过。未执行远程部署、Git 提交或推送。
- T152 完成；下一任务为 T153。继续开发前等待决策者验收确认。

## 2026-09-10 T153 非 OpenAI 协议适配与显式阻断完成

- 按供应商协议拆分调用边界：Anthropic 使用 Messages `/messages`、顶层 `system` 和原生图片 block；Google Gemini 使用 `:generateContent`、`systemInstruction`、`contents`/`parts`、`responseMimeType=application/json` 和 `inlineData`；百度与智谱使用各自声明的 Chat Completions 地址并归一化 choices 响应。实现依据供应商官方接口说明：[Google GenerateContent](https://ai.google.dev/api/generate-content)、[百度千帆 Chat Completions](https://cloud.baidu.com/doc/qianfan-api/s/3m7of64lb)、[智谱 HTTP API](https://docs.bigmodel.cn/cn/guide/develop/http/introduction)。
- 目录能力声明收窄：百度、智谱当前仅展示已适配的 chat；Anthropic、Google 只展示当前运行时已适配的 chat/vision（Google 另含 embedding）；OpenAI-compatible、Azure、custom/local 保留各自已声明类型。模型配置表单显示实际协议名称，避免把未适配媒体能力伪装成可用。
- 变更影响矩阵：`catalog.PROVIDER_TYPES/PROVIDER_PROTOCOLS` → 模型目录 REST → `ModelConfigView.vue` 的供应商/能力选择；`native_structured_chat` → 需求分析 `OpenAICompatibleRuntime` → 结构化结果解析；`inference_probe` → 测试连接 REST → 模型配置页的实际调用测试。旧的凭据加密、路由矩阵、权限和兼容协议请求字段保持回归。
- 第一轮专项：T153 原生协议、T152 兼容协议、模型发现和需求分析调用方共 31/31 通过；覆盖正常、图片输入转换、认证头、路径、JSON 响应、能力不匹配前置阻断和无供应商请求副作用。
- 第二轮回归：后端 `apps` 全量 340/340；Django system check 通过；`makemigrations --check --dry-run` 无变更；前端 Node 测试 12/12；Vite 生产构建通过。
- 真实本地联调：管理员页面加载模型配置工作台，目录 REST HTTP 200 返回协议和能力字段；新浏览器页 `auth/me`、模型列表、供应商目录、路由矩阵均 HTTP 200，Console 错误 0；打开“添加模型”并切换 Anthropic 后显示 `Anthropic Messages`，模型类型仅为 chat/vision。
- 链路测试证据：无 Authorization 的本地目录探针仍为 401；管理员 JWT 目录请求为 200；专项验证百度 vision 在请求前返回 `capability_not_supported` 且 `urlopen` 未调用。未执行真实供应商计费调用，保留至 T160；未新增依赖、环境变量或数据库迁移，未远程部署、提交或推送 Git。
- T153 完成；下一任务为 T154。完成报告后暂停等待决策者确认。

## 2026-09-10 T151 浏览器 Console/Network 与用户验收通过

- 使用本地管理员 `platform_admin` 通过 Playwright MCP 登录 `http://127.0.0.1:5173/`，进入 `/workspace/models` 完成模型配置工作台验收；凭据未写入项目文件、配置或日志。
- 页面真实加载 2 个模型配置和 8 条路由矩阵；模型列表、官方目录和路由矩阵请求均 HTTP 200；页面正确展示文本模型能力和视觉/向量能力不匹配提示。
- 真实操作验证 DeepSeek“禁用”确认提示、停用状态与启用数量刷新、路由重新计算、再次启用和原状态恢复；两次 PATCH 均 HTTP 200，最终两个模型均恢复为启用。
- 浏览器 Console 错误 0；Network 未发现未解释的关键请求失败、凭据泄露或状态不同步。T151 代码、REST、自动化测试、真实短调用和浏览器用户验收全部通过。
- T151 完成；下一任务为 T152。未执行远程部署、依赖安装、环境变量变更、数据库迁移或 Git 推送。

## 2026-09-10 模型配置启用/禁用入口补充（T151 范围内）

- 用户验收前补充模型接入列表的“启用/禁用”操作；复用现有 `PATCH /api/configs/models/:id/` 的 `is_active` 字段，不新增数据库迁移、依赖或环境变量。
- 禁用操作增加明确确认提示，说明该模型将不再参与新的任务路由；成功后刷新模型状态、启用数量和路由矩阵；启用操作可直接恢复。
- 变更影响矩阵：`ModelConfigView.vue` → `updateModelConfig` → `ModelConfigViewSet`/`ModelConfigSerializer` → `ModelRouteResolver`；覆盖模型列表状态、路由候选、管理员权限和错误提示。删除、连接测试、用量和编辑链路未改变。
- 第一轮专项：`apps.configs.tests_t010`、`tests_mr01_routing`、`tests_mr02_api` 共 17/17 通过。
- 真实本地 API：DeepSeek 配置禁用 HTTP 200、列表状态为 `is_active=false`，重新启用 HTTP 200，最终状态恢复为启用；真实页面入口仍为模型配置列表。
- 第二轮回归：后端 `apps` 全量 331/331；Django system check 通过；`makemigrations --check --dry-run` 无变更；前端 Node 测试 12/12；Vite 构建通过。
- 当前结论：启用/禁用功能实现、REST 闭环和自动化验证完成；未开始 T152。T151 最终标记仍等待浏览器 Console/Network 用户验收门禁。

## 2026-09-10 T151 真实 DeepSeek 验收与回归复核

- 本次仅处理 T151，未开始 T152，未执行远程部署、依赖变更、迁移变更或 Git 推送。
- 网络恢复：后端已通过 Windows UAC 以管理员权限重启；本机未配置 HTTP/HTTPS 代理。前端 `5173`、后端 `8000` 和 `/api/health/` 均返回 HTTP 200。
- 真实模型验收：通过本地 REST `/api/configs/models/7/test-connection/` 的 `mode=inference` 对已配置 DeepSeek `deepseek-chat` 发起一次最小 `Reply OK` 调用；响应 HTTP 200，`stage=inference`、`inference_verified=true`、`ok=true`，耗时约 1359ms，未携带项目数据。
- 第一轮专项：T151 与配置/路由/模型目录专项 35/35 通过。
- 第二轮回归：后端 `apps` 全量 331/331；Django system check 通过；`makemigrations --check --dry-run` 显示无变更；前端 Node 测试 12/12；Vite 生产构建通过。
- 真实本地 API 边界：匿名读取模型列表 HTTP 401；管理员模型列表 HTTP 200（2 个模型）；管理员路由矩阵 HTTP 200（8 行，8 行均含 `capability_contract`）；viewer 读取模型列表 HTTP 403；DeepSeek 实际推理 HTTP 200。
- 变更影响矩阵：统一契约 → 路由解析/候选筛选 → 模型配置 REST/路由矩阵 → `ModelConfigView.vue` 能力展示；自动化调用方、旧配置字段、权限边界和迁移一致性均已回归。
- 当前结论：T151 的代码、REST、真实供应商短调用、自动化测试和本地 API 边界均已通过；但当前 CUA 仍无浏览器表面（`apps=[]`、`browsers=[]`），无法由本代理完成工作台 Console/Network、页面操作和浏览器用户验收，因此暂不把 T151 标记为最终完成，也不进入 T152。

## 2026-09-09 今日开发进度归档：T151 统一模型运行时契约（部分完成，待验收）

- 今日完成范围：开始执行阶段27的 T151；新增 `backend/apps/configs/contracts.py`，建立统一模型调用契约、能力矩阵、能力校验和旧任务类型兼容映射，覆盖需求分析、用例生成/评审、智能体、报告、截图/视觉和知识模型边界。
- 后端接入：`configs.routing` 的路由结果携带统一契约；`core.llm.manager` 使用同一能力矩阵筛选模型；路由矩阵 REST 响应新增 `capability_contract`，前端模型配置页展示输入/输出能力及所需模型类型。
- 影响链路：统一契约 → 路由解析/候选模型筛选 → 路由矩阵 REST → `ModelConfigView.vue` 展示；未改动数据库模型、迁移、依赖、环境变量、密钥和远程部署。
- 第一轮专项：T151 契约/路由测试 22/22 通过；过程中发现 retrieval 能力映射与旧管理器兼容性问题，已修复并复测通过。
- 第二轮回归：后端 `apps` 全量（按 `tests*.py` 模式）331/331 通过；Django system check 通过；`makemigrations --check --dry-run` 无变更；前端 Node 测试 12/12 通过；Vite 生产构建通过；`5173` 与后端健康接口均 HTTP 200。
- 真实本地 API：通过 `5173` 代理完成临时管理员认证、路由矩阵读取和能力契约断言；临时联调账号/数据已清理。这里的 HTTP 200 仅作为传输证据，未据此宣称功能验收完成。
- 当前结论：T151 代码、REST、前端展示和自动化测试已完成，但暂不标记为完成。当前 CUA 无可用浏览器表面（`apps=[]`、`browsers=[]`，无法打开 IAB），因此尚未完成浏览器 Console/Network 监控、页面操作、错误/重试/权限/边界和用户验收门禁。

### 今日遗漏与未关闭事项

- T151 尚缺：浏览器真实页面验收，重点检查路由矩阵请求、模型配置页无未解释 Console 错误、Network 状态与业务响应一致，以及空数据、能力不匹配、401/403、服务失败和重试反馈。
- T151 尚缺：在本地配置并明确授权后，用 DeepSeek 或千问完成一次无项目敏感数据的真实短调用；该验证只能证明 AITS 供应商链路，不能替代 Codex 自身的 `chatgpt.com/backend-api/codex/` 会话连接。
- 阶段27的 T152-T161 均未开始，不能因为 T151 的契约矩阵已接入就提前进入协议适配、统一业务调用或官方模型目录任务。
- T160 所需的目标服务器/受控代理真实供应商验收仍未执行；本轮没有远程部署、镜像更新、数据库迁移、依赖安装、Git 提交或推送。
- 历史待处理项继续保留：RAG 二阶段规划待审核，以及状态中已有的页面/真实视觉模型验收、T107-T110/T025/T039 架构依赖和 T145/T146 历史口径复核；本次未删除、未擅自关闭这些事项。

### 下次恢复点

- 仍停留在 T151，不开始 T152。
- 首先完成浏览器 Console/Network 和工作台用户验收；若用户需要真实模型验证，再使用已配置且获授权的 DeepSeek/千问执行单次脱敏短调用并记录响应业务语义。
- 验收通过后，补写 T151 完成记录并等待用户明确确认，再按依赖进入 T152。

## 2026-09-09 T150 Skill 业务页面前后端闭环整改

- 实现范围：需求文档 `parse`、深度 `analyze`、截图 `screenshot-analysis` 接入 `SkillExecutionService`；用例生成 `create`、评审 `review` 接入对应内置 Skill；新增“用例评审”内置 Skill 及迁移 `skills.0008_seed_case_review_skill`。
- 前端闭环：需求分析页和用例生成页读取 REST 返回的 `skill_execution`，显示自动调用的 Skill、版本、完成/失败/等待补充状态和服务消息；未开放第三方源码直接执行，安装页仍只负责校验、审批、安装、回滚和卸载。
- 变更影响矩阵：`SkillExecutionService` → `SkillManager`/内置 Skill 注册 → 需求分析 REST → `RequirementAnalysisView.vue`；`SkillExecutionService` → 用例生成 REST → `CaseGenerationView.vue`；原有 AgentGraph、Skill 安装与权限审计链路保持不变。`linkages` 和 `select` 仍由确定性业务服务负责，没有伪造不匹配的 Skill 状态。
- 链路测试证据：专项 `apps.skills apps.agents apps.requirement_analysis apps.case_generation` 150/150；后端全量 332/332；Django check、迁移检查通过；Vite 生产构建通过；真实本地 HTTP 依次验证需求解析 200、深度分析 200、用例生成 201、用例评审 200，四个响应均返回 `skill_execution.status=completed`；联调数据已清理并恢复原模型启用状态。
- 边界验证：既有需求/用例 API 测试继续覆盖空数据、字段错误、401、403、服务失败和旧数据读取；T150 新增响应断言验证 Skill 状态。性能、APP、接口、脚本等未形成对应业务页面的真实 Skill 闭环，不因本任务提前标记完成；远程部署未执行。
- 当前状态：T150 实现与自动化/本地联调已完成，待决策者在本地页面刷新后验收；验收前不进入下一业务任务。
- 任务统计同步：当前台账已纳入阶段27的 T151-T161，为 165 个唯一 `T` 任务 + 7 个唯一 `MR` 任务 = 172 个唯一任务标识；任务表统计口径同步为 173 行，T116 的历史重复行仍只计一次。

## 2026-09-09 模型调用全链路整改计划（阶段27）

- 本次审计确认整改范围较大，不能只修复一个 Qwen 参数或只修复需求分析页面。连接测试、需求分析、视觉分析、用例生成、五轮评审、智能体、Embedding 和后续 RAG 入口存在不同的协议、能力、路由、状态和错误处理路径，必须按统一运行时契约逐条收敛。
- 已新增独立计划文档 [`doc/LLM_CALL_CHAIN_REMEDIATION_PLAN.md`](LLM_CALL_CHAIN_REMEDIATION_PLAN.md)，将整改拆分为 T151-T161：运行时契约、OpenAI 兼容协议、非兼容协议、统一路由、需求/视觉、用例生成/评审、智能体、官方模型目录、Embedding 边界、观测反馈和最终验收。
- 已同步 `doc/TASKS_V5.0.md` 阶段27，并新增 T161“官方模型目录与选择器闭环”。该阶段只完成规划和台账，不代表业务代码已修复；当前首个候选任务为 T151，等待决策者审核计划后再开始编码。
- 新增产品要求：选择任意供应商并填写连接信息后，模型配置页应优先展示该供应商官方目录中的模型名称/模型 ID；没有官方目录 API 时使用带来源、版本和更新时间的官方目录快照。必须区分官网支持、当前 Key 可访问和当前端点可调用，不能把官网全量模型直接标成当前可用。
- 已确认的当前根因证据：服务器“所选模型实际调用”可通过；本地同一供应商的结构化需求分析请求超时；在相同请求中补齐 Qwen `enable_thinking=false` 后可返回 HTTP 200。说明 Key 和基础网络不是唯一问题，连接测试与业务调用的协议/参数/超时链路不一致是 P0 整改项。
- 计划边界：不伪造确定性结果为模型验证通过；不允许显式路由失败时静默跨供应商；不在本阶段顺便实现完整 RAG 二期；不执行数据库、依赖、环境变量或远程部署变更。
- 阶段27门禁：每次只开发一个任务；每个任务均须完成后端 Service→REST→前端→真实本地 API 联调，两轮测试和 `PROJECT_STATUS.md` 记录；T160 的真实供应商调用必须另获明确授权。
- 2026-09-09 契约补充：HTTP 200/201 只代表传输层状态，不代表业务通过。已将 Console/Network 监控、响应业务语义、持久化/副作用、加载/空/成功/字段错误/401/403/404/409/5xx/超时/网络中断/能力不匹配、重复提交、取消、重试、旧数据兼容和失败恢复写入 `CONTRACT_ENFORCEMENT.md`、核心开发契约、`TASKS_V5.0.md` 和本整改计划；存在未解释控制台错误或未覆盖边界时不得完成任务。
- 2026-09-09 契约文档链补漏：核心契约原先只引用 PRD、TECH_ARCH、TASKS 和 `.env.example`，存在专项计划、启动审计、项目状态和项目级规则未被强制纳入的结构性遗漏。现已将根目录/`doc` 规则、执行补充、启动审计、状态、任务、PRD、技术架构、环境模板及当前专项方案统一登记；新增需求/任务/架构/环境约束若未同步登记到对应文档，禁止进入编码。

## 2026-09-09 T150 模型调用失败提示与本地网络阻断整改

- 根因判定：服务器“所选模型实际调用”已通过，证明该供应商地址、模型名和 Key 在服务器运行环境有效；本地失败页明确返回 `WinError 10013`，属于 Windows 本机 Django/Python 外连被网络策略拒绝，不是 Key 错误。当前生效模型路由仍以显式配置为准，不因本地失败而偷偷切换供应商。
- 代码修复：`RequirementModelAdapter` 现在区分“没有可用模型”和“已找到模型但调用失败”；调用失败会列出已尝试的模型，并安全传递 HTTP 401/403、429、超时、DNS/TCP/本机网络策略等可行动原因。`analyze_requirement_document` 不再把真实调用失败写成“已使用确定性基线”；模型调用失败仍不落库、不生成伪造分析结果。
- 安全边界：错误信息不包含 API Key、Authorization、代理凭据或完整敏感 URL；明确路由仍不绕过策略自动改用其他供应商，避免数据跨供应商外发。
- 第一轮专项测试：需求分析模型选择/错误链路、确定性分析、网络错误分层 21/21；业务闭环专项 `apps.skills apps.agents apps.requirement_analysis apps.case_generation` 151/151。
- 第二轮回归：后端全量 333/333；前端 Vite 生产构建通过；本地前端 `5173`、后端 `/api/health/` 均 HTTP 200；无新增依赖、环境变量或数据库迁移；远程部署未执行。
- 待验收：在本地放行后端进程外连或配置受控代理后，使用“所选模型实际调用”重新验证；服务器已通过的配置不需要因本次提示修复而重置 Key。
- 本地运行环境复核：普通受限执行环境到供应商 443 被拦截，但高权限同机复核可建立 TCP/HTTPS 并得到供应商预期的 401；已仅重启本地 Django 后端为可出网进程，前端、数据库和配置未改动，健康接口 HTTP 200。该限制属于当前开发代理/沙箱启动边界，不是应用代码或供应商 Key 故障。
- 进程复核补充：发现旧 Django 自动重载进程与新后端同时监听本地 8000，浏览器因此可能随机命中旧进程并继续得到 `WinError 10013`；已仅关闭确认属于本项目的旧进程，目前 8000 仅保留可出网后端，健康接口 HTTP 200。未修改前端缓存、数据库、Key 或远程部署。
- 本地启动固化：`scripts/start-dev.ps1` 新增默认开启的 `NetworkEnabled` 参数；非管理员启动时，Django 后端通过 Windows UAC 请求高权限，前端仍普通启动，后端继承已有 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量。当前机器没有实际代理地址，因此本次固化采用高权限出站方式，不伪造或硬编码代理；PowerShell 语法、前端 5173、后端 8000 健康检查均通过。

## 2026-09-08 当日部署验收归档与下次恢复点

## 2026-09-09 文档一致性与待审核项复核

- 已补充 `doc/PRD_V5.0.md` 第 12.3.9 节：第三方代理、自建境外 Gateway、境外直连和跨地域模型连接必须经过“草稿→待审核→审核通过→已验证→已启用”的独立审批生命周期；涉及生产数据、敏感数据、跨地域传输或高费用连接时触发 HITL/双人确认；连接状态、项目范围、数据去向、费用、密钥归属、有效期和审计要求已明确。
- 已同步补充 `doc/AITS-LLM-代理兼容架构改进方案.md` 第 4.1.1 节；该方案仍是二期评审稿，尚未写入 `TASKS_V5.0.md`，未开始代码实现。
- 本次新增 P0 产品补漏：PRD 第 21.5/21.6、技术架构第 22.4，以及任务 T147/T148。T147 负责管理员邀请/开通同事、平台角色、项目成员、项目角色、密码重置和审计闭环；T148 负责显式配置并展示唯一用户访问地址，避免把公网入口、后端端口、Docker、数据库、Redis 和 SSH 地址混淆。
- 当前服务器用户入口以部署配置为准；本次已知外部入口为 `http://124.222.221.128:8090/`，其中 `8090` 是前端用户入口，后端 `8000`、数据库、Redis、Docker 内网地址和 SSH 地址都不应提供给普通同事。T148 完成后该入口不再依赖人工记忆，而由 `PUBLIC_APP_URL` 在管理员工作台展示和生成邀请链接。
- 任务台账因新增 T147/T148 重新核算为 153 个唯一 `T` 任务 + 7 个唯一 `MR` 任务 = 160 个唯一任务标识，任务表 161 行；T116 仍是唯一历史重复行，不重复计数。
- 用户最新实测状态：国内及其他可达供应商模型可以正常添加；当前未解决的是境外模型在该部署环境中无法完成目录/连接验证，不能据此判定模型配置功能整体不可用。此前模型发现 HTTP 500 的旧记录已由 2026-09-09 T146 修复记录覆盖，保留在历史时间线中，不作为当前状态。
- 全量扫描 `doc/` 下 9 个 Markdown 文件后，确认存在以下未关闭事项：RAG 二阶段规划等待用户审核；T043-R、T047、T094、T095、T049、T043-L 等页面或真实视觉模型验收仍标记为待决策者验收；T107-T110 及 T025/T039 存在状态记录中的架构/依赖缺口；T145/T146 的旧部署未完成描述与 2026-09-09 的 T146 修复记录存在时间线冲突，需要后续统一状态口径。
- 任务统计已按 `TASKS_V5.0.md` 实际任务表重新计算：151 个唯一 `T` 任务 + 7 个唯一 `MR` 任务 = 158 个唯一任务标识；任务表共 159 行，唯一重复为 T116 保留两行历史定义。阶段 9 实际包含 15 个任务，原记录写成 14 是漏计 T047-L。未删除任何任务或需求，已修正统计口径和阶段计数。
- 已区分“需求中定义的待审核状态”和“开发台账中尚未完成的用户验收”：知识库审核流程 T026 已有实现和专项测试，不属于未处理的审核需求；本次新增的是 LLM 连接配置审批，不得用现有知识审核流程替代。
- 当前不自动关闭上述事项、不修改历史完成记录、不把二期方案提前加入任务清单；下一步应由决策者确认二期方案和待验收项的处置顺序后，再逐项整改或归档。
- 2026-09-09：按决策者确认开始处理 T147。新增账号动作令牌模型和迁移 `users.0002_accountactiontoken`，支持管理员邀请/重发/撤销激活链接、管理员生成一次性密码重置链接，以及公开激活和密码重置接口；用户管理工作台新增邀请同事、重发邀请、重置密码、撤销链接和安全复制入口，新增激活/重置页面。令牌只保存摘要，明文只在管理员本次响应中返回，不写日志；新账号默认停用且无密码，激活后才允许登录。
- T147 同步补齐账号审计模型和迁移 `users.0003_accountauditevent`，记录邀请、重发、撤销、激活、生成重置链接、完成重置及平台权限变更；管理员工作台可查看最近审计事件，审计元数据过滤密码、令牌和其他敏感字段。
- T147 第一轮专项测试 31/31、Django system check、迁移一致性检查通过；第二轮后端全量 327/327、迁移应用、前端生产构建通过；真实本地 HTTP 已验证管理员登录→邀请→一次性激活→新账号登录及对应审计记录闭环。决策者已完成页面验收，T147 标记为已完成；按明确指令，本轮及后续未收到“更新远程部署”前均不执行远程迁移、重建或容器更新。
- 历史记录：当时下一任务为 T148“用户访问地址与部署入口展示”。T148 已按本地开发和验证范围完成，未更新远程部署；境外模型出网问题仍保持单独遗留项，不与本任务混做。当前工作转入 T150 Skill 业务页面闭环整改。
- 2026-09-09：补修需求智能分析空项目入口 bug。无项目时“导入需求”按钮不再无解释地禁用，点击后跳转到“项目与智能体”页面，由用户显式创建项目；需求分析页不自动创建项目、不隐式选择项目。已有项目但角色无写权限时继续拒绝写操作并给出联系项目管理员提示。该修复仅涉及本地前端，生产构建通过；随后已完成 Skills 文件夹上传整改，详见下一条记录。
- 2026-09-09：修复 Skills 第三方目录上传。Skills 安装工作台现在支持单个压缩包和浏览器文件夹选择（`webkitdirectory`）；文件夹必须包含 `SKILL.md`，浏览器提交相对路径和内容，后端执行重复路径、路径穿越、文件数（≤500）、总大小（≤50MB）和确定性 SHA-256 校验，不保存或执行第三方源码。原有 Manifest、权限声明、校验、审批、安装和回滚流程保持不变；远程部署仍按指令不更新。

- 用户已在目标服务器部署的 V5 入口完成注册，账号标识为 `admin`；注册账号默认是 `viewer`，已通过服务器容器命令将其提升为平台管理员，并能进入“模型配置”页面。聊天中出现过服务器登录凭据和账号密码，后续必须更换，不得写入项目文件或日志。
- 目标部署信息：服务器项目目录为 `/opt/aits-v5-release-20260908`，Compose 项目为 `aits_v5`；新验证前端容器为 `aits_v5_validation_frontend`，宿主机端口为 `8090`，后端容器为 `aits_v5-backend-1`。旧 `aits-*` 容器仍与 V5 并存，公网入口没有切换到旧系统。
- 端口结论：云安全组截图显示全部 TCP 端口（含 22、80、8090）已放行；服务器 UFW 为 inactive；用户已能访问 `8090`。本开发环境仍无法直接 TCP 连接目标服务器，判断为当前开发环境自身的出站限制，不能据此认定目标服务器端口关闭。
- 历史部署验收记录：模型配置页 DeepSeek“刷新模型目录”请求 `/api/configs/models/discover/` 曾连续返回 HTTP 500；同页公开目录 `/api/configs/models/catalog/` 返回 HTTP 200，认证、项目和路由矩阵接口均返回 HTTP 200。该问题已由后续 T146 修复记录覆盖，境外模型出网仍是独立环境遗留项。
- 版本/部署判断：当前工作区 `HEAD` 与本地记录的 `origin/master` 都是 `0f9177f`，但 T146 连接安全与错误分层代码、测试和部署文件仍有未提交变更，不能假定 GitHub 已包含这些变更；当前环境通过 SSH 无法读取 GitHub 远端，也无法直接 SSH 目标服务器。截图中的 Compose 重建命令未显式加载 `.env.remote`，出现 `POSTGRES_* variable is not set` 警告并重建了 `aits_v5-db-1`；未执行删除卷操作，数据卷应仍保留，但必须用正确环境文件复核数据库健康状态。
- 当日未完成且必须作为下次第一顺序的事项：等待当前 Compose 命令结束；在 `/opt/aits-v5-release-20260908` 使用 `--env-file .env.remote` 正确重建/检查 `db`、`backend`、`celery_worker` 和 `celery_beat`；确认数据库健康、Redis 连接和后端日志；确认容器内是否包含 `validate_outbound_endpoint`、`tcp_blocked`、`local_network_blocked` 等 T146 标记；再用服务器端无 Key 的 DeepSeek 网络预检（预期 401 也可证明出网）和一次明确授权的真实短调用定位 500。
- 下次部署修复前禁止事项：不得执行 `docker compose down -v`、删除 `postgres_v5_data`/`redis_v5_data`、覆盖 `.env.remote`、在聊天中发送 API Key/密码，或在未确认镜像来源前盲目覆盖前端/后端容器。前端验证容器是独立容器，单纯 `git pull` 不会自动更新 8090 的静态构建产物；若确认镜像过旧，需要从已确认源码重建并重新创建该容器。
- 历史任务边界：当时只完成部署连通性、管理员入口和问题归档，未提交/推送 Git；后续已按用户确认继续本地业务整改。当前以文档顶部的 T150 状态为准，远程部署仍未执行。

## RAG 二阶段规划草案（待用户审核，2026-09-08）

- 根据决策者要求，将 RAG 作为下一阶段独立规划，不直接进入代码实现。
- 已更新 `doc/PRD_V5.0.md`：补充 RAG 二阶段的产品定位、用户场景、知识生命周期、PostgreSQL FTS 与 BM25 边界、固定向量维度、证据型回答、敏感数据外发、成本确认/限流/取消/回滚、错误交互和专项验收指标。
- 已更新 `doc/TASKS_V5.0.md`：新增阶段24、T133-T144，按“契约与维度策略 → pgvector → Embedding/敏感检测/路由 → 索引成本与版本回滚 → LlamaIndex适配 → PostgreSQL FTS 混合检索 → 证据型回答 → API → 前端 → 评测验收”拆分；MR-05 的知识库模型接入转入该阶段。
- 已更新 `doc/TECH_ARCH_V5.0.md`：补充 RAG 分层架构、固定维度和版本化向量存储、索引生命周期与原子回滚、Embedding 外发策略、PostgreSQL FTS 与可选 BM25 边界、证据型回答契约、LangGraph 接入、安全、评测和成本控制。
- 规划判断：现有知识库解析、审核和基础检索可复用；当前 JSON 向量与离线 HashVectorizer 不满足生产 RAG，因此采用兼容迁移和双路径验证，不推倒重写。
- 本次仅修改规划文档，未修改业务代码、数据库、依赖或环境变量；已完成文档一致性检查，未执行 RAG 实现测试，等待用户审核规划是否合格。

## 模型供应商出网阻断审计（2026-09-08）

- 用户反馈：模型配置页选择“所选模型实际调用”时，三个已配置模型均提示测试未通过，并出现 `WinError 10013`。
- 已确认：前端 `5173`、后端 `8000` 和 `/api/health/` 均 HTTP 200；失败发生在后端向供应商发起外部请求的网络层。PowerShell 外网请求也失败，说明不是前端选择器或单个供应商协议导致。
- 已确认：当前进程没有 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`，WinHTTP 为直连；运行环境存在 `codex_sandbox_offline_block_outbound` 出站阻断规则及回环阻断规则。
- 处理结果：尝试增加仅限项目虚拟环境 `python.exe` 的 TCP 443 出站放行时，Windows 要求管理员权限，规则未修改；没有删除或停用整体安全策略，没有修改 Key、代码、数据库或依赖。
- 架构判断：若生产服务器也没有供应商出网或代理，所有用户的连接测试、需求分析、用例生成、Embedding 和智能体模型调用都会失败；若只有当前受限开发环境阻断，生产服务器具备直连/代理能力则不构成同一故障。
- 规划整改：在 `PRD_V5.0.md` 增加服务器端网络门禁、环境未就绪状态和目标地址安全校验，在 `TECH_ARCH_V5.0.md` 增加 Django/Celery 运行身份、直连/代理、DNS/TCP/TLS、SSRF 防护和分层错误要求，在 `TASKS_V5.0.md` 将工作拆为 T145 出网预检与 T146 连接诊断/安全校验闭环。
- 当前阻断：需要管理员放行目标运行环境的最小供应商出站策略，或提供后端/Celery 可继承的受控代理；在此之前不能完成真实模型验收，也不应把 RAG 生产验收标记为通过。

## 网络门禁规划合规复审整改（2026-09-08）

- 已修正任务规则冲突：自动化测试默认使用 Mock；只有明确授权的连接测试和目标环境最终验收允许一次无业务数据短调用，禁止自动重试和无授权计费。
- 已拆分职责：T145 只做服务器端出网、代理和运行身份预检；T146 负责后端 Service、REST 契约、前端反馈、错误分层和目标地址安全校验。
- 已补充 SSRF 防护边界：供应商域名/端口白名单、解析 IP 校验、回环/私网/链路本地/云元数据地址拦截、DNS rebinding 防护和重定向绕过防护。
- 已补充部署落地约束：Django、Celery Worker 和任务容器分别注入代理；明确代理认证、CA 证书和轮换，不假设项目 `.env` 会被所有启动脚本自动读取。
- 已补充费用与健康检查约束：T145 网络预检不调用收费模型，禁止用定时收费调用作为健康检查；真实短调用只在目标环境最终验收时执行一次。
- 复审结果：PRD、TASKS、TECH_ARCH 和 PROJECT_STATUS 的 T145/T146 引用、任务统计和依赖图已同步；本次仍未修改代码、数据库、依赖、环境变量或防火墙。

## T146 连接测试安全校验与错误分层实现记录（2026-09-08）

- 已完成后端请求前安全校验：内置供应商域名白名单、HTTPS/端口限制、解析 IP 校验、回环/私网/链路本地/云元数据地址拦截、禁止重定向绕过校验；`local` Provider 保留仅访问本机回环地址的明确例外。
- 已完成错误分层：DNS、TCP/本机网络、TLS、代理、供应商 HTTP、鉴权、额度和目标不安全等错误转换为脱敏稳定码；历史 `local_network_blocked` 保持兼容。
- 已完成 REST 与前端闭环：模型连接测试页面展示失败阶段和处理建议；异常信息不包含 Key、Authorization、代理凭据或完整敏感 URL。
- 第一轮专项：T146 后端安全/错误/REST 测试 25/25，前端模型连接反馈测试 11/11。
- 第二轮回归：后端全量 321/321；`manage.py check` 通过；`makemigrations --check --dry-run` 无变更；`pip check` 无依赖问题；前端全量 11/11；Vite 生产构建通过；前端、后端和健康接口均 HTTP 200。
- 真实供应商调用：未在当前受限开发环境执行。当前机器仍因 WinError 10013 阻断外连，T145 的目标服务器/受控代理预检与一次明确授权的真实短调用仍是外部验收门禁，不能在本地把该项标记为通过。
- 变更范围：修改 `backend/apps/configs/services.py`、`frontend/src/views/ModelConfigView.vue`；新增 T146 后端与前端测试及 `frontend/src/utils/modelConnection.js`；无新增依赖、环境变量或数据库迁移；未修改防火墙，未提交或推送 Git。
- 下一步：由管理员为目标 Django/Celery 运行身份提供最小供应商出网或受控代理，执行 T145；通过后再按无业务数据、不自动重试、单次短调用规则完成目标环境真实验收。

## T145 服务器隔离验证部署记录（2026-09-08）

- 已连接目标服务器并确认 Ubuntu 24.04、Docker/Compose 可用；服务器对多个供应商完成无 Key 的网络预检，DeepSeek 返回 401、通义返回 404、智谱返回 200，证明服务器具备实际外网访问能力；OpenAI 端点仍需目标模型配置后单独验证。
- 已在 `/opt/aits-v5-release-20260908` 建立隔离发布目录，上传当前源码和前端构建产物；保留原 `.env.remote`、数据库卷和 Redis 卷，未执行数据卷删除。
- 已切换 `aits_v5` 的 backend、celery_worker、celery_beat 到当前验证镜像；数据库原有 43 项未应用迁移已完成应用，Django check、健康接口和 Worker Redis 连接通过。Compose 因依赖关系重新创建了 v5 db 容器，但持久化卷保持不变。
- 已启动独立前端验证容器 `aits_v5_validation_frontend`，监听服务器 8090；服务器本机访问前端和 `/api/health/` 代理均 HTTP 200。公网 80 的旧 `aits` 系统未切换，若外部访问 8090 被云安全组拦截，需要放行 TCP 8090，或另行批准切换公网入口。
- 当前为“模型连接验证镜像”：复用旧运行时基础层并补齐当前 Python 依赖，暂未重新下载 Tesseract 系统包；模型连接测试不依赖 Tesseract，最终生产镜像仍需使用稳定 Debian 镜像源补齐 OCR 系统依赖。
- 用户验收前置：v5 数据库为初始化状态，尚无平台管理员和模型配置；用户需先在 `http://124.222.221.128:8090/` 注册账号并告知账号标识，再完成管理员授权和模型 Key 配置。禁止在聊天中发送模型 Key。

### TODAY ARCHIVE (2026-09-07)

- Completed scope: MR-04, unified model routing and five-round semantics for intelligent case generation and review.
- Final status: backend, REST API, frontend entry, model selectors, failure feedback, historical record display and real local API checks are complete. The next session starts at MR-05.
- Test evidence: case-generation focused 25/25; backend full suite 313/313; Django check passed; migration check reported no changes; Vite production build passed; frontend, backend and health URLs returned HTTP 200.
- API evidence: anonymous model-options request returned 401; authenticated temporary admin read both case-generation and case-review model options with HTTP 200; temporary account was deleted.
- Services: local frontend and backend remain available. If backend code does not hot reload, restart using start-dev.cmd.
- Data/configuration: no new migration, dependency or environment variable; no API key was written or exposed; historical generation records were retained.
- Git: no commit, tag or remote push was created. The next session must inspect the working-tree diff and must not roll back existing changes.
- Next startup order: read PROJECT_STATUS, TASKS_V5.0, PRD_V5.0, TECH_ARCH_V5.0, the core contract and startup audit; check both services; confirm MR-04 archive; then begin MR-05 other model-consuming features (agent, report and knowledge model) through the backend to REST to frontend to real API to acceptance loop.
- Boundary: do not start MR-06 or MR-07 before explicit confirmation, and do not push Git automatically.

### ???????2026-09-07?

- ???????MR-04?????/???????????
- ??????????REST API??????????????????????????? API ?????????? MR-05??????????
- ????????????? 25/25????? 313/313?Django check ???`makemigrations --check --dry-run` ?? No changes detected??? Vite ???????`http://127.0.0.1:5173/`?`http://127.0.0.1:8000/`?`http://127.0.0.1:8000/api/health/` ? HTTP 200?
- ?? API ??????? `/api/case-generation/model-options/` ?? 401??????????`case_generation` ? `case_review` ????????? 200?????????
- ????????????????????????????????????????????? `start-dev.cmd` ?????
- ???????????????????????????????????? API Key???????????
- Git ?????????????????????????????????????????????
- ?????????????`TASKS_V5.0.md`?`PRD_V5.0.md`?`TECH_ARCH_V5.0.md`????????????????????? MR-04 ????? MR-05?????????????????????????????????????REST?????? API???????????
- ??????????????????????? MR-06 ??????? MR-07 ?????????? Git?

### MR-03 需求分析与视觉分析模型入口（2026-09-07）

- 已完成：需求文档与截图文档均提供模型选项接口和前端选择入口，默认继承平台全局路由；也支持本次分析临时选择兼容模型，并显示当前生效模型、来源和路由错误。
- 已完成：需求分析适配器接入统一路由，显式临时模型失败时返回可理解错误；未显式选择时保留历史兼容路径，截图能力按视觉/全模态能力过滤，OCR 证据链仍保持确定性基线。
- 已完成：补齐空数据、能力不匹配、未配置、401 和服务失败反馈；前端选择值只在本次分析请求提交，不覆盖平台或功能级配置。
- 第一轮专项：`apps.requirement_analysis` 与 `apps.configs` 109/109；MR-03 专项 3/3；前端模型目录/路由 Node 测试 8/8；Vite 生产构建通过。
- 第二轮集成：后端全量 308/308、Django check、迁移检查、`git diff --check` 和前端生产构建通过；本地前后端入口及健康接口 HTTP 200。
- 真实 API 联调：登录后读取需求文档模型选项返回 `requirement_analysis` 和可选模型；匿名请求返回 401；临时联调账号、项目和文档已清理。
- 兼容边界：本任务只接入需求分析/视觉分析入口；用例生成、评审、智能体、报告和知识模型入口按 MR-04/MR-05 单独迁移，避免跨任务修改。
- 页面补漏：修复模型选择区和截图识别提示位于 `WorkspaceShell` 外部导致固定侧栏遮挡的问题，现已纳入需求工作区内容流，随工作区边距和响应式布局正常显示。
- 性能补漏：发现首个需求文档包含 2,814 个测试点，页面原先一次性渲染完整列表导致浏览器主线程阻塞；现改为首屏展示 80 条并按“加载更多”分批追加，完整分析数据仍保留。
- 数据诊断：该记录的 `coverage_report.analysis_method` 为 `deterministic_evidence_baseline`，并标记“没有可用的需求分析模型”；402 个功能点按确定性基线每个固定生成 7 条，恰好得到 2,814 条，确认不是大模型生成结果。
- 路由整改：当存在可用需求分析模型但调用失败时，不再静默写入确定性替代结果；分析请求明确失败并将文档置为失败状态，避免把基线结果误当成真实需求分析。无任何兼容模型配置时仍保留历史基线能力并明确标记。
- 当前配置核验：本地配置存在全局路由和千问视觉模型；一次最小推理探测被当前 Windows 进程网络权限以 `WinError 10013` 拒绝，不能据此判定 Key 无效，需要先恢复本机网络权限后再重新执行模型分析。
- 本次补漏验证：需求分析与配置专项 113/113、后端全量 309/309、前端模型测试 8/8、Vite 构建和差异检查通过；未修改或删除历史 2,814 条记录，待模型调用恢复后通过“深度分析”重新生成并保留历史版本。
- 联合场景补漏：确定性基线不再把相邻功能点自动标成 `sequence`；仅保留识别到明确调用/依赖、展示或数据关联的关系，并过滤同一模块内无证据的展示关系。该文档重新按基线计算为 20 个候选联合场景，而非 401 个伪场景；历史 401 条记录保留并在页面标记为历史基线，重新深度分析后更新。
- 补漏验证更新：需求分析专项 43/43、后端全量 310/310、前端生产构建和差异检查通过。
- 下一任务：MR-04“用例生成/评审路由与五轮语义”，等待用户确认后开始。

### MR-02 全局与功能路由 REST/API 及配置入口（用户截图验收通过，2026-09-07）

- 已完成：新增管理员路由策略 REST API，提供完整路由矩阵、全局/功能策略 upsert、能力过滤、最终生效模型、来源和错误信息；严格返回安全模型摘要，不暴露 API Key 或加密字段。
- 已完成：模型配置工作台新增“平台模型路由”区域，支持平台全局默认、功能模型继承全局、备用模型、备用切换和确定性基线开关；展示需求分析、视觉分析、用例生成、评审、智能体、报告和知识库等 8 个路由功能。
- 已完成：补齐前端 API 封装、路由来源中文化、加载/空数据/服务失败/401/403/字段错误反馈和保存重试路径；未配置或能力不匹配时显示可理解原因。
- 验收修复：路由卡片改为等高伸展布局，保存按钮统一贴齐卡片底部；保存前显示“保存此大模型”，保存成功后显示绿色“大模型已保存”状态，重新选择模型、备用模型或切换策略后恢复保存动作。
- 验收修复：路由卡片下拉框改为深色背景、浅色文字和青色边框，避免浏览器默认白底在深色工作台中过度刺眼。
- 第一轮专项：配置后端 71/71、前端 Node 测试 8/8、Vite 生产构建通过；修正一次错误的目录测试命令后重新执行成功。
- 第二轮集成：后端全量 305/305、Django check、迁移检查、前端生产构建通过；真实管理员登录→读取 8 项矩阵→保存全局模型→需求分析生效来源验证通过；匿名 API 返回 401，前端入口和后端健康接口 HTTP 200。
- 验收：用户通过实际工作台截图检查并反馈按钮对齐、保存状态、文案和下拉框样式，修复后确认“好的，继续开发”；当前环境无可用浏览器自动化表面，因此保留自动化表面限制记录，不阻断用户截图验收结论。
- 下一任务：MR-03“需求分析与视觉分析模型入口”（已完成）。

### MR-01 统一模型路由核心与数据契约（2026-09-07）

- 已完成：新增 `ModelRoutingPolicy` 数据模型，支持平台全局默认、功能级主模型、备用模型、备用切换开关和确定性基线开关；既有 `ModelConfig.is_default` 保留为兼容路径，不追溯性改变历史配置。
- 已完成：新增统一路由解析服务，固定“本次临时选择 → 功能绑定 → 平台全局 → 旧按类型默认”的兼容优先级，执行能力匹配；显式绑定能力不匹配时安全阻止，不静默切换错误模型。
- 已完成：新增 `ModelManager.resolve_route` 与 `execute_routed`，只有路由策略明确允许时才尝试备用模型；原有 `candidates`、`execute_with_fallback` 保留，避免影响此前已验收功能，后续 MR-02～MR-05 逐项迁移到新路由入口。
- 数据库：新增并应用 `configs.0006_modelroutingpolicy` 迁移；未新增第三方依赖、环境变量或明文凭据。
- 第一轮专项：配置应用 67/67，通过 Django system check、迁移检查；覆盖全局/功能/临时优先级、能力不匹配、备用策略和同模型校验。
- 第二轮集成：后端全量 302/302、前端生产构建、前后端真实入口与健康接口 HTTP 200；既有 T009、模型配置、需求分析和用例生成测试保持通过。
- 下一任务：MR-02“全局与功能路由 REST/API 及配置入口”，范围限路由策略 API、能力过滤和模型配置工作台入口。

### T046-L/T095 五轮递进式模型用例生成整改（2026-09-07）

- 用户明确的业务语义：五轮不是把整份需求重复生成五次，而是围绕同一份需求和已完成的深度分析，依次补充主流程、异常/权限、边界/状态、跨模块链路、最终遗漏与回归风险；每轮只返回新增用例，跨轮去重但保留不同场景。
- 已完成：用例生成适配器现在按 1～5 轮分别调用配置模型，输入包含原需求正文、功能模块、功能点、测试点、联合场景和已有用例；每轮校验来源功能点/联合场景，只接收结构化新增用例。
- 已完成：修复原第 4 轮按“功能点+类型”粗暴去重导致模型细化场景被压缩的问题，改为按来源、类型、标题、步骤、预期结果和联合场景做语义签名；覆盖报告记录每轮新增数、累计数、模型轮次和降级原因。
- 已完成：需求分析、用例生成和用例评审可使用 chat/multimodal/vision 文本模型；Qwen 默认兼容地址、供应商鉴权和模型路由已接入，配置 Qwen 视觉/全模态模型时可用于文本需求分析。前端新增五轮明细、降级提示和“重新生成”入口。
- 第一轮专项：需求模型路由、五轮生成、评审、自动化筛选和 REST 工作台 36/36 通过；新增五轮模型调用和跨轮场景保留测试，Qwen 默认地址测试通过。
- 第二轮集成：后端全量 295/295、Django system check、迁移检查、前端生产构建通过；重启后的 `5173/`、`8000/` 和健康接口均可访问。真实供应商五轮生成未自动执行，避免在未获明确费用授权时消耗用户模型额度；页面可通过“重新生成”启动真实五轮调用。

### T010/T097 模型配置整改（2026-09-07）

- 用户反馈：供应商切换后模型类型和名称目录不完整，通义千问已配置 Key 无法有效连接测试。
- 已完成：新增供应商目录协议和能力归一化；选择供应商后展示公开参考目录，填写密钥后通过后端按供应商协议分页同步账号目录；未知能力模型保留为“其他/待确认能力”，不因前端分类猜测而丢失；模型 ID 上限扩展到200字符。
- 已完成：扩展模型能力类型为全模态、图像生成、视频、音频、语音合成、语音识别、实时交互、重排序、三维生成和其他，并应用 `configs.0005_alter_modelconfig_model_name_and_more` 迁移。
- 已完成：千问目录使用官方 `/api/v1/models` 分页接口；兼容推理地址和原生目录地址分离，保留地域/业务空间/Coding Plan 地址提示。供应商鉴权分别支持 Bearer、Anthropic `x-api-key`、Google `x-goog-api-key`、Azure `api-key`。
- 已完成：连接测试拆为“目录连接与模型可见性”和“所选模型实际调用”；实际调用仅在用户明确选择时发起一次短请求，不自动重试，不把目录 HTTP 200 冒充模型调用成功；错误区分密钥、权限、地域、额度、地址、模型未列出、网络和响应格式问题。
- 已完成：模型配置页面新增目录同步、全量分页、搜索、全部类型显示、未知能力保留、千问地址说明、失败/部分加载反馈、自定义部署名称保存和实际连接测试反馈；修复自定义模型选择器保存 `__custom__` 哨兵值的问题。
- 第一轮专项：后端模型配置与供应商发现测试 59/59，前端模型目录工具测试 6/6，覆盖分页、去重、取消过期请求、空目录、循环分页、各供应商鉴权、千问原生目录、错误脱敏和实际调用探测。
- 第二轮集成：后端全量 291/291、Django check、migrate --check、pip check、前端生产构建通过；本地 `5173/`、`8000/`、`8000/api/health/` 均 HTTP 200。此前一次组合命令因在 backend 目录使用了错误的 `.venv` 相对路径，未将该次结果计入；随后已用正确路径重跑并记录以上结果。
- 本次连接失败复核：用户提供的千问 Key 未写入数据库，仅在临时进程中验证；使用 `https://dashscope.aliyuncs.com/compatible-mode/v1` 与 `qwen-max` 时目录测试和实际调用均成功（实际调用 HTTP 200，`inference_verified=true`）。先前裸域名调用得到 HTTP 404，确认是地址缺少 `/compatible-mode/v1`，不是 Key 无效。
- 本机故障修复：截图中的 `WinError 10013` 来自占用 8000 端口的旧受限 Django 进程；清理重复自动重载进程后以前台 `--noreload` 进程接管端口，真实本地 HTTP API 的千问实际调用返回 200。服务层新增 `local_network_blocked` 脱敏诊断；专项测试 14/14、后端全量 292/292 通过。
- 限制：真实供应商成功与否取决于用户 Key、地域/业务空间、账户额度、模型授权和网络；没有有效凭据不能安全地宣称“任何模型连接测试通过”。浏览器工具当前无可用浏览器，本次未完成人工页面点击验收。
- 下一步：用户可在 `/workspace/models` 选择供应商；填写与供应商地域匹配的 Key 后点击“刷新模型目录”，再选择模型和类型保存；连接测试先选目录测试，需验证真实调用时再显式选择实际调用。

## 最新续接审计与服务恢复（2026-09-07）

- 本节优先于下方历史“下一任务”“待验收”和遗留问题摘要；历史记录保留，不将历史测试视为本次验证。
- 服务恢复：当前 `.venv` 缺少已锁定的 pypdf 5.9.0、python-docx 1.1.2、Pillow 11.3.0、pytesseract 0.3.13，后端 URL 导入时报 `ModuleNotFoundError: docx`。按现有 requirements.txt 补齐，连带安装 lxml 6.1.3；未修改依赖清单、数据库结构或业务代码。运行 start-dev.cmd 后后台启动未稳定恢复，补用同一虚拟环境、现有开发配置及原 Fernet 密钥启动后端（本次为 --noreload，后续代码改动需重启后端）。
- 当前访问验证：5173 首页、src/main.js、8000 根接口、8000/api/health/ 以及 5173/api/health/ 均 HTTP 200。浏览器工具无可用浏览器，本次没有完成浏览器页面操作验收。
- 第一轮：文档加载及需求解析专项 11/11 通过。第二轮：后端全量 278/278、前端生产构建、Django check、migrate --check、pip check 通过。全量和构建证据分别保留在被忽略的 `.runtime/recovery-regression.log`、`.runtime/recovery-frontend-build.log`；PowerShell 将原生 stderr 包装为 NativeCommandError，Django 测试实际退出码为 0 且结果 OK。
- 已归档结论：2026-09-06 最后归档明确 T047-L、T094、T095、T049、T131 完成代码、REST、前端入口、真实代理及重复操作验证；真实视觉模型语义验收仍待配置视觉模型，不能由 OCR 安全降级测试替代。
- 已证实的前置遗漏：当前源码未找到 T107 AgentRuntimeAdapter、T108 LlamaIndex RAG 适配、T109 MCP 网关、T110 HITL/checkpoint 实现，对应 core/runtimes、core/rag、core/mcp、core/hitl 目录缺失，Git 提交标题亦未找到对应任务完成记录。T025/T033/T036/T039 已向后推进，存在任务依赖缺口。
- 架构差异：T039 当前 apps/agents/graph.py 为自写顺序 AgentGraph，未使用 LangGraph StateGraph；T025 当前为 JSON 向量、离线 HashVectorizer 与余弦检索，未达到任务要求的 pgvector + PostgreSQL FTS 混合检索。真正 BM25 不属于 RAG 二阶段 P0，需后续独立评估。现有测试通过不能证明这些架构要求已交付。
- 历史台账差异记录：旧版本曾统计为 137 个唯一任务编号、TASKS 总数 136、旧状态总数 133，并漏计 T047-L；本次已按当前任务表重新核算并修正为 151 个唯一 T 任务、7 个唯一 MR 任务、158 个唯一任务标识，T116 重复行仅保留追溯，不重复计数。历史摘要中的待验收和旧下一任务仍需按用户验收结果逐项归档，不能删除历史记录代替状态修正。
- Git：恢复前工作区干净，HEAD 为 512d382；已有 baseline/20260904-pre-batch 及多个附注检查点，最近创建的为 checkpoint/20260906-T131-ui-zh。本次未提交、打标签、推送或回滚；当前不是一次确认五项任务的批次。
- 建议顺序：服务恢复（已完成）→统一台账并逐项补齐 T107、T108/T025、T109、T110/T039 的依赖与架构缺口→需要开放 API 的能力紧接前端真实联调和验收→重新审计后再恢复 T050。
- 下一业务任务：暂缓 T050。建议首先确认 T107 统一智能体运行时边界，范围限输入/输出/事件/错误契约、默认单智能体路径和测试，不启用可选多智能体框架。其余补漏逐任务确认，不在本次审计中跨任务实现。

## 当前进度

- 已完成：T001 Django 项目与 Python 虚拟环境
- 已完成：T002 多环境配置与 Celery
- 已完成：T003 Vue 3 前端项目
- 已完成：T004 UserProfile 模型与 Django Admin 集成
- 已完成：T005 用户注册、登录、JWT 刷新和当前用户信息 API
- 已完成：T005A 科技感登录/注册入口、JWT 状态管理和基础工作台框架
- 已完成补漏：T005A 认证状态响应式同步与可配置 API 基址下的 JWT 刷新
- 已完成补漏：T005/T005A 注册和登录统一支持“用户名或邮箱”单账号入口，并兼容旧 API 请求格式
- 已完成：T006 五种角色的操作级权限体系
- 已完成：T007 创建 `configs` app 与 `ModelConfig` 模型
- 已完成：T008 API Key Fernet 加密存储
- 已完成：T009 `ModelManager` 模型管理器
- 已完成：T010 模型配置 REST API
- 已完成：T097 模型配置页面与真实API联调（V5.2纵向闭环）
- 已完成：T011 创建 `PromptConfig` 模型
- 已完成：T012 实现 `PromptManager` 提示词管理器
- 已完成：T013 编写并预置11个场景默认提示词
- 已完成：T014 实现提示词配置 REST API
- 已完成并验收：T113 提示词配置页面与真实API联调
- 已完成：T015 创建`projects` app及项目/成员模型
- 已完成补漏：T126 用户与角色权限管理前后端闭环
- 已完成：T016 实现项目REST API
- 已完成：T017 创建 agents app 与 Agent 模型
- 已完成：T018 实现智能体REST API
- 已完成并验收：T114 项目与智能体配置页面及真实API联调（已修复旧Vite缓存导致的 project-agent.css 路径报错，并补齐模型供应商联动目录）
- 已完成：T019 创建 environments app 与 Environment 模型（2026-09-05 用户要求继续新任务后执行）
- 已完成：T020 环境 REST API（CRUD、项目隔离、配置权限及凭据保护）
- 已完成并验收：T096 环境管理页面与真实 API 联调
- 已完成并验收：T021 环境健康检查器、手动API与环境页检查入口
- 已完成：T022 每5分钟环境健康检查 Celery 定时任务
- 已完成：T023 创建 knowledge app 与 KnowledgeBase/Document/QAPair/Embedding 模型
- 已完成：T024 文档加载与分块（TXT/Markdown/PDF/DOCX）
- 已完成：T025 向量化与项目隔离检索服务
- 已完成：T026 知识审核机制（文档与问答通过/拒绝/暂缓）
- 已完成：T027 知识库 REST API（知识库/文档/问答 CRUD、文档上传解析、向量化、审核、项目隔离检索）
- 已完成：T115 知识库页面与真实 API 联调（文档上传、解析、向量化、QA、检索与审核）
- 已完成：T028 创建 skills app（Skill 模型和 BaseSkill 基类）
- 已完成：T029 实现 SkillManager（注册、加载、匹配、推荐）
- 已完成：T030 实现内置 Skills（第一批：接口测试、AI测试、用例生成）
- 已完成：T031 实现内置 Skills（第二批：性能测试、APP测试、安全测试、截图识别）
- 已完成：T032 实现 Skills REST API（CRUD、启用/禁用）
- 已完成：T127 自定义 Skill 运行时绑定（受控运行时、输入输出校验、超时/异常隔离、前端执行入口与真实 API 测试）
- 已完成：T128 第三方 Skill 来源协议（本地包、GitHub、SkillHub、版本化下载包适配与统一清单校验）
- 已完成：T129 第三方 Skill 安装与校验（版本锁定、文件/提交哈希验证、管理员审批、安装审计及卸载回滚）
- 已完成：T130 Skill 运行权限隔离（最小权限、默认拒绝、越权审计与安全失败）
- 已完成：T131 第三方 Skill 管理前端与安装生命周期 REST API（来源添加、清单/权限查看、校验、审批、安装、回滚、卸载及错误反馈）
- 已完成：T132 Skills 扩展全链路联调（本地/GitHub/SkillHub 模拟来源、受控调用、权限审计与撤销）
- 已完成：T033 定义 AgentState（对话、环境、意图、需求分析、执行、打断、通知字段）
- 已完成：T034 实现感知与理解节点（意图识别）
- 已完成：T035 实现检索与规划节点
- 已完成：T036 实现决策与路由节点
- 已完成：T037 实现需求分析与用例生成节点
- 已完成：T038 实现反思与报告节点
- 已完成：T039 实现图构建器并集成 Celery
- 已完成：T040 创建 requirement_analysis app（RequirementDocument/RequirementAnalysis 模型）
- 已完成：T041 实现在线文档适配器
- 已完成：T042 文档解析器（PDF/Word/Excel/Markdown/Swagger/在线文档/OCR安全解析）
- 已完成：T043 需求深度分析器（功能模块、功能点、关联关系、流程与数据流）
- 已完成待验收：T043-R 统一需求来源证据链与低置信度拦截（保留来源位置、原文片段、置信度和人工确认标记）
- 已完成：T044 联合功能识别器（跨模块依赖、展示、状态和数据联动测试点）
- 已完成：T045 创建 `case_generation` 应用与 `CaseGenerationRecord` 模型
- 已完成：T046 五轮用例生成器（初始、对比、补全、修正、最终确认）
- 已完成待验收：T047 五轮用例自动评审器（初评、对比评审、偏差修正、复审、最终报告及模型复核）
- 已完成整改：T043-L/T049 截图视觉模型链路补漏；结构化模型请求在存在截图文件时携带受限大小的原图 Data URL 和 MIME 类型，视觉模型可读取像素并结合 OCR 证据输出；截图来源也允许仅提供 OCR 正文并进入持久化解析，前端同步提供正文兜底入口。专项14/14、后端全量277/277、迁移检查、Django check、前端生产构建和本地截图 OCR API 联调通过，待决策者验收视觉模型真实语义结果。
- 已完成：T048 自动化用例筛选器（自动化判断、难度、技术栈和优先级）
- 已完成：T116 Skills 页面与真实 API 联调（补齐 T032 的前端闭环）
- 已完成待验收：T094 需求分析页面与真实 API 联调（需求文档导入、解析、深度分析、联合功能识别、项目权限和错误反馈）
- 已完成待验收：T095 用例生成页面与 REST API 闭环（生成、评审、自动化筛选、覆盖度展示）
- 已完成待验收：T049 截图识别分析器（OCR 证据、页面元素、控件、区域和测试点提取）
- 已完成待验收：T043-L 需求分析模型链路整改（ModelManager/PromptManager、结构化校验、重试和降级）
- 已完成待验收：T043-L DeepSeek 结构化兼容修复（禁用推理输出、JSON 内容片段解析、证据关联校验，避免已配置模型因空 content 或无关输出误回退/误采纳）
- 已完成待验收：T046-L 用例生成模型链路整改（结构化用例校验、五轮兼容和安全降级）
- 当前模块闭环顺序：T127 受控运行时 → T128 来源协议 → T129 安装与校验 → T130 权限隔离 → T131 管理前端 → T132 全链路联调
- V5.3全历史合规审查（2026-09-04）：已完成整改并通过复核。已核对任务清单、契约、状态记录、前后端路由/API、迁移、权限、配置、真实联调证据与Git历史；补建确认任务台账、审查记录、基线/检查点标签，并将连接测试改为可测试的通用供应商探测器。后续批量开发继续受检查点门禁约束。
- 文档基线：V5.1架构调整、V5.2纵向交付调整和V5.3批量审查均已人工确认；任务总数为133个，新增T113-T132补齐前端闭环与Skills扩展要求，所有任务按依赖而非编号执行

## 最近一次会话交接

- 2026-09-06：按决策者要求将Skills扩展需求正式写入PRD 11.5，并在TASKS_V5.0新增T127-T132：自定义运行时绑定、第三方来源协议、安装校验、权限隔离、管理前端和全链路联调。第三方代码默认不执行，必须版本/哈希校验、管理员审批、最小权限和可撤销审计。

- 2026-09-06：完成T127。Skill模型新增runtime_key、timeout_seconds及0004迁移；新增受控runtime执行边界，禁止执行用户提交的Python，校验输入/输出JSON契约，限制超时并隔离异常；Skills API新增execute动作；工作台Skills列表增加Run入口、JSON输入和成功/失败反馈；专项测试2/2、后端全量204/204、Django check、迁移和前端构建通过。修复刷新按钮点击无效问题，并应用0004迁移解决/api/skills/返回500。Git提交：b4fa8e8、399e02d。下一任务T128。
- 2026-09-06：完成T128。新增第三方 Skill 来源协议，统一支持本地包、GitHub、SkillHub 和版本化下载包；来源地址、版本、作者、许可证及七类运行权限声明均执行严格校验，禁止凭据地址、路径穿越、未知来源和未完整声明权限的清单；适配器仅做发现和元数据规范化，不下载或执行第三方代码。专项测试6/6、后端全量210/210、Django check、迁移检查和前端构建通过。下一任务T129。
- 2026-09-06：完成T129。新增 SkillInstallation 模型及安装服务，支持版本锁定、50MB大小限制、SHA-256文件哈希/提交哈希校验、管理员审批门禁、安装失败记录、卸载与回滚状态；第三方代码不导入、不执行，回滚仅停用关联Skill并保留审计记录。专项测试3/3、后端全量213/213、Django check、迁移检查和前端构建通过。迁移 skills.0005_skillinstallation 已加入。下一任务T130。
- 2026-09-06：完成T130。新增 SkillPermissionAudit 及运行时权限守卫，网络、文件、数据库、外部命令、模型、知识库和环境凭据默认拒绝，仅允许已安装清单明确声明的能力；每次允许/拒绝均记录权限、结果、调用者和脱敏上下文字段，审计失败时安全拒绝。专项测试4/4、后端全量217/217、Django check、迁移检查和前端构建通过。迁移 skills.0006_skillpermissionaudit 已加入并应用。下一任务T131。
- 2026-09-06：T130验收修复。新增管理员只读权限审计 API `/api/skills/permission-audits/` 及工作台 `Skill audits` 页面，支持加载、空数据、失败重试、401/403反馈；真实前端页面与后端接口返回200，专项测试6/6、后端全量219/219、前端构建通过。T131继续负责第三方来源安装审批等完整管理页面。
- 2026-09-06：T130 Admin 500 修复。权限审计记录禁止手工新增、修改和删除，避免 `/admin/skills/skillpermissionaudit/add/` 空记录提交触发数据库错误；新增只读 Admin 回归测试，专项测试7/7、后端全量220/220、前端构建通过。浏览器 `content_scripts.js removeChild` 为外部扩展脚本提示，与平台代码无关。
- 2026-09-06：完成T131。新增管理员安装生命周期 API `/api/skills/installations/` 及 verify/approve/install/rollback/uninstall 动作，复用来源清单、版本和哈希校验服务；新增工作台 `Skill installations` 页面，支持来源添加、权限查看、受控校验、审批、安装、回滚、卸载和加载/空数据/字段错误/401/403/服务失败反馈。专项测试3/3、后端全量223/223、Django check、迁移一致性检查和前端生产构建通过；本地前后端服务保持HTTP 200。下一任务T132。
- 2026-09-06：T131验收补漏。工作台新增本地 Skill 文件选择器，限制50MB，浏览器计算SHA-256并将文件转为受控校验载荷，导入请求后自动完成完整性校验，再进入管理员审批；不下载或执行第三方代码。后端专项3/3、前端生产构建通过。
- 2026-09-06：完成T132。安装审批后自动绑定受控 Skill 运行时，新增 `invoke` API 和工作台 Invoke 操作；调用必须声明权限并经过 T130 守卫，允许与拒绝均写入审计，回滚/卸载后调用安全失败。专项测试2/2（含本地、GitHub、SkillHub 模拟发现及安装→调用→撤销）、后端全量225/225、Django check、迁移一致性检查和前端生产构建通过；本地前后端服务保持HTTP 200。Skills扩展阶段完成，下一任务恢复T042。
- 2026-09-06：完成T042。新增需求文档解析器，统一支持PDF、Word、Excel、Markdown、Swagger/OpenAPI、在线文档和图片OCR安全失败边界；实现10MB大小限制、UTF-8规范化、XLSX XML单元格提取、在线适配器复用及RequirementDocument解析状态推进。补充Python依赖`Pillow==11.3.0`、`pytesseract==0.3.13`及本机Tesseract 5.5.3，真实PNG文字识别通过。专项测试5/5、后端全量230/230、Django check、迁移一致性检查和前端生产构建通过。下一任务T043。
- 2026-09-06：完成T043。新增确定性的需求深度分析器，按标题和句子拆解功能模块与功能点，识别依赖/展示/数据关联，生成业务顺序、数据流、正向/异常/边界测试点和覆盖度报告；可将RequirementDocument分析结果持久化并保留多次分析历史。专项测试4/4、后端全量234/234、Django check、迁移一致性检查和前端生产构建通过。下一任务T044。
- 2026-09-06：完成T044。新增跨模块联合功能识别器，基于T043结果识别依赖、展示、状态联动和数据联动，生成带证据的联合场景与联动测试点，并持久化更新覆盖度统计；无跨模块证据时安全返回空结果。专项测试3/3、后端全量237/237、Django check、迁移一致性检查和前端生产构建通过。下一任务T045。
- 2026-09-06：完成T045。新增`case_generation`应用与`CaseGenerationRecord`模型，记录项目/需求文档关联、生成轮次、总用例数、自动化/手工用例数和生成状态；加入项目边界校验、Admin和`case_generation.0001_initial`迁移。专项测试2/2、后端全量239/239、迁移应用与一致性检查、Django check和前端生产构建通过。下一任务T046。
- 2026-09-06：完成T046。新增五轮确定性用例生成器，执行初始生成、需求对比、遗漏补全、偏差修正和最终确认；覆盖功能点正向/异常/边界及跨模块联动，生成稳定用例ID、自动化标记、优先级、步骤、预期结果和覆盖度报告，并持久化到生成记录。新增`cases`与`coverage_report`字段及0002迁移。专项测试3/3、后端全量242/242、迁移应用与一致性检查、Django check和前端生产构建通过。下一任务T047。
- 2026-09-06：完成T047。新增五轮确定性用例自动评审器，执行初评、需求对比评审、偏差修正、复审和最终报告；检查必填字段、重复编号、正向/异常/边界覆盖并保留问题严重级别、修正记录和审批结论。生成记录新增review_rounds与review_report字段及0003迁移；专项测试3/3、后端全量245/245、迁移应用与一致性检查、Django check和前端生产构建通过。下一任务T048。
- 2026-09-06：完成T048。新增自动化用例筛选器，基于联动类型、人工交互标记和步骤复杂度判断自动化适配性，输出自动化/手工建议、低中高难度、Playwright或pytest/requests技术栈、P0/P1优先级及解释原因，并回写生成记录统计。专项测试3/3、后端全量248/248、Django check、迁移一致性检查和前端生产构建通过。下一任务T049。

 - 2026-09-06：完成T095代码闭环。新增用例生成 REST API `/api/case-generation/` 与工作台 `/workspace/case-generation`，支持项目隔离、五轮生成、评审、自动化筛选、覆盖度展示、加载/空数据/字段错误/401/403/服务失败反馈；专项测试14/14、后端全量261/261、Django check、迁移一致性检查、前端生产构建和本地HTTP联调通过。等待决策者验收。

- 2026-09-06：完成T049代码闭环。新增证据优先截图识别服务与 `screenshot-analysis` API，基于 OCR 坐标和置信度提取文字、控件、区域及可验证测试点；无 OCR 证据时安全返回待人工确认；Dockerfile 增加 Tesseract 与 `chi_sim` 系统依赖；需求分析页面增加截图识别入口。专项测试2/2、后端全量264/264、Django check、迁移一致性检查、前端生产构建和本地HTTP联调通过。等待决策者验收。
- 2026-09-06：T049本机环境补漏。下载 `chi_sim.traineddata` 与英文语言包到被Git忽略的 `backend/.runtime/tessdata`，解析器自动发现项目级语言目录并使用稀疏文本模式；真实背包截图可提取“材料、仓库、兑换、批量、整理、132/200”等证据，但平均置信度约46.8%，继续强制人工确认。专项15/15、后端全量264/264和前端构建复测通过。

 - 2026-09-06：完成T043-L代码闭环。新增结构化模型适配器，按需求/截图场景路由对话或视觉模型，使用 PromptManager 合并提示词，使用 ModelManager 执行候选模型重试与备用降级；模型输出结构和证据引用均校验，不可信时安全回退确定性基线并记录原因。专项33/33、后端全量267/267、Django check、迁移一致性检查和前端生产构建通过。T046/T047模型化改造仍未完成。

 - 2026-09-06：完成T046-L代码闭环。用例生成器接入结构化模型适配器，校验功能来源、类型、步骤和预期结果后继续五轮去重/补齐/修正/确认；模型失败或结构不可信时回退确定性五轮生成并记录 `model_warning`。专项10/10、后端全量268/268、Django check、迁移一致性检查和前端生产构建通过。T047模型化改造仍未完成。
 - 2026-09-06：决策者验收通过T021、T096、T114页面闭环，确认环境健康检查、环境管理、项目与智能体配置的正向、异常、权限和错误反馈路径可用。
 - 2026-09-06：完成T047模型化整改。新增CaseReviewModelAdapter，复用ModelManager/PromptManager和结构化运行时；模型评审结果执行用例范围、严重级别、修正字段及证据引用校验，并纳入五轮评审报告。模型失败或输出不可信时回退确定性评审并记录model_warning；用例生成工作台展示评审方式、问题和降级原因。专项11/11、后端全量268/268、迁移检查、Django check、前端生产构建和本地API联调通过，等待决策者验收。
 - 2026-09-06：T047/T095重复点击卡顿修复。评审完成后再次点击直接返回已持久化结果，自动化筛选完成后再次点击直接返回既有结果；前端按钮显示“已评审/已筛选”并禁用重复请求。补充幂等 API 回归测试，专项4/4、后端全量269/269、迁移检查、Django check、前端生产构建和本地前后端HTTP 200通过。
 - 2026-09-06：T047评审中文显示补漏。模型评审保留英文原文供审计，同时归一化常见问题与建议为中文；历史英文评审记录在 API 读取时也自动本地化，避免页面出现英文评审内容。专项11/11、后端全量270/270、迁移检查、Django check、前端生产构建和本地前后端HTTP 200通过。
 - 2026-09-06：T047评审中文展示补漏。严重级别统一输出高/中/低，历史报告和模型报告为缺失或重复问题编号补充稳定唯一 ID，前端按中文级别展示并避免重复键渲染。专项12/12、后端全量278/278、Django check、迁移检查和前端生产构建通过。
 - 2026-09-06：T043-L DeepSeek兼容补漏。DeepSeek推理模型默认关闭thinking，避免结构化响应因`reasoning_content`耗尽预算而出现空`content`；兼容文本片段JSON，并增加需求证据锚点校验，拒绝无关模型结果后安全回退确定性基线。专项5/5、后端全量265/265、迁移检查、Django check、前端生产构建和本地前后端HTTP 200通过；已配置DeepSeek连接与结构化调用验证通过。等待决策者验收。

### 当前遗留问题与处理顺序

1. T094、T095、T049、T043-L、T046-L仍需决策者浏览器验收。
2. 生产或其他开发数据库必须执行`python manage.py migrate`，否则Skills新增运行时字段会导致列表接口500；本地数据库已应用skills.0004_runtime_binding。
3. T127当前运行时是确定性的受控回显实现，尚未连接第三方代码或外部模型；第三方代码在T128-T130完成来源、审批和隔离前不得执行。
4. 本地提交与检查点标签完成后暂不推送远程；后续任务仍按“后端→前端→真实API联调→验收”逐任务推进。

- 2026-09-06：完成T094实现。新增需求文档与需求分析 REST API，支持项目范围内的手工录入、文件上传、在线链接和截图 OCR 来源，提供解析、深度分析、联合功能识别动作及历史分析读取；新增需求分析工作台页面、项目筛选、空数据/成功/字段错误/401/403/服务失败反馈和真实代理入口。修复截图来源持久化解析分支与空截图校验，新增需求文档上传目录和10MB配置项。专项测试23/23、需求分析全量23/23、后端全量254/254、Django check、迁移检查、前端构建和本地服务联调通过。Git检查点：`checkpoint/20260906-T094-requirement-analysis`。等待决策者页面验收。
- 2026-09-06：T094验收补漏。修复需求分析页面将平台管理员角色 `platform_admin` 误判为只读导致“导入需求”按钮禁用的问题；前端生产构建通过，等待浏览器刷新后验收。
- 2026-09-06：T094视觉补漏。修复需求分析页全局标题样式覆盖导致“需求智能分析”文字低对比度不可读的问题，增加页面级高亮标题样式；前端生产构建通过，等待浏览器刷新后验收。
- 2026-09-06：T094联合识别补漏。联合识别按钮在未完成深度分析时明确禁用；识别完成但没有跨模块关系时显示可理解的空结果和补充要求，避免用户误判为功能失效；专项测试23/23、前端构建和本地页面联调通过。
- 2026-09-06：T043验收补漏。针对截图 OCR 仅得到少量文本导致测试点过少的问题，扩展每个功能的正向、输入校验、权限拒绝、依赖失败、边界值、重复提交和状态恢复基线；截图来源额外增加页面元素、导航切换、列表/网格和操作反馈视觉基线，并明确标注需人工确认。专项测试6/6、需求分析全量25/25、后端全量256/256、迁移检查和前端构建通过。截图精确元素识别仍保留在后续T049任务边界内。
- 2026-09-06：T043-R整改完成。统一解析证据结构覆盖文本、PDF、Word、Excel、Swagger、在线文档和OCR；RequirementDocument持久化证据、解析置信度及警告；截图中文OCR语言包缺失时停止输出低可信文本，深度分析对低置信度来源只生成视觉基线并标记待人工确认；前端展示证据数量、置信度、警告和确认状态。专项测试27/27、后端全量258/258、Django check、迁移一致性检查和前端生产构建通过。下一步等待用户验收。

- 2026-09-06：完成T116。工作台新增Skills入口和管理页面，接入真实/api/skills/，支持全局/项目筛选、列表、创建、编辑、删除、启停、JSON契约校验、权限/401/403/失败反馈；前端构建通过，5173页面HTTP 200，真实platform_admin登录经5173代理加载7项内置Skill成功。此前T032后的前端闭环遗漏已补齐，停在T042。

- 2026-09-06：按决策者要求优化交付流程：后端每完成一个可操作功能，必须立即完成对应前端入口、真实本地API联调和严格异常/权限调试，前端闭环未通过不得开始下一个后端业务功能。新增T116 Skills页面与联调任务，纠正T032后直接推进后端任务的流程遗漏；当前暂停在T116。

- 2026-09-06：完成T041。新增需求分析在线文档适配器协议和安全实现，支持腾讯文档、飞书、Notion、语雀、Swagger/OpenAPI及通用网页识别，HTTP(S)限制、10MB上限、UTF-8规范化、Swagger JSON校验和通用回退均已覆盖；专项5/5、全量202/202通过，迁移一致性、Django check和diff check通过，未访问真实外部站点，停在T042。

- 2026-09-06：完成T040。新增requirement_analysis app及RequirementDocument、RequirementAnalysis模型，支持项目归属、文件/在线链接/截图/手工来源、版本和解析状态，分析结果保存模块/功能/联合链路/测试点/覆盖度JSON；接入Django Admin并应用requirement_analysis.0001迁移。专项2/2、全量199/199通过，迁移一致性、Django check和diff check通过，停在T041。

- 2026-09-06：完成T039。新增agents.graph轻量图构建器，串联感知、理解、检索、规划、决策、需求分析、用例生成/评审、反思、学习和报告节点；新增agents.run_graph Celery任务，支持序列化状态执行、暂停/取消保留和异常安全返回。专项3/3、全量197/197通过，迁移一致性、Django check和diff check通过，停在T040。

- 2026-09-06：完成T038。新增agents.reporting，提供reflect_node结果汇总/失败重规划判断、learn_node可审核学习候选和report_node结构化最终报告，包含会话、项目、意图、Skill和知识数量追踪且不写入外部系统；专项3/3、全量194/194通过，迁移一致性、Django check和diff check通过，停在T039。

- 2026-09-06：完成T037。新增agents.requirement，提供需求分析结构化输出、正向/异常/边界三类用例草稿生成及覆盖性评审结果，前置状态缺失和评审缺失类型均有明确错误/报告；专项4/4、全量191/191通过，迁移一致性、Django check和diff check通过，停在T038。

- 2026-09-06：完成T036。新增agents.decision，按需求分析、用例生成、接口/AI/UI/APP/性能/安全测试等意图生成稳定路由，未知意图安全进入reflect；pause进入wait_for_input并保留paused状态，stop/cancel进入cancelled；同步扩展AgentState.route字段。专项3/3、全量187/187通过，迁移一致性、Django check和diff check通过，停在T037。

- 2026-09-06：完成T035。新增agents.planning，retrieve_node调用知识库审核检索并写入带来源和相关度的knowledge_context，plan_node调用SkillManager推荐并写入selected_skills、execution_order和ready计划，支持按意图安全兜底；专项4/4、全量184/184通过，迁移一致性、Django check和diff check通过，停在T036。

- 2026-09-06：完成T034。新增agents.nodes，提供幂等perceive_node消息归一化、understand_node本地确定性意图识别（需求分析、用例生成、接口/AI/UI/APP/性能/安全测试、知识检索、环境检查及other兜底）、URL/文档实体提取和环境/需求文档澄清问题；专项5/5、全量180/180通过，迁移一致性、Django check和diff check通过，停在T035。

- 2026-09-06：完成T033。新增agents.state，定义可序列化AgentState、Message、执行状态和打断信号类型，提供new_agent_state初始化工厂及validate_agent_state身份/消息/生命周期校验；专项3/3、全量175/175通过，迁移一致性、Django check和diff check通过，停在T034。

- 2026-09-06：完成T032。新增Skills REST API，提供全局/项目Skill列表、详情、创建、编辑、删除和toggle启停；平台管理员可管理共享Skill，项目成员按角色和项目范围受控，普通成员只读，响应包含分类/状态标签。专项17/17、全量172/172通过，迁移一致性、Django check和diff check通过，停在T033。

- 2026-09-06：完成T031。新增性能测试（JMeter/Locust选择）、APP测试、安全测试和截图识别四个内置Skill，均提供输入校验、授权门禁或确定性计划输出；新增skills.0003幂等种子迁移。专项13/13、全量168/168通过，迁移一致性、Django check和diff check通过，停在T032。

- 2026-09-05：完成T030。新增接口测试、AI测试、用例生成三个内置Skill，均实现BaseSkill运行时契约、输入校验和结构化计划输出；新增幂等种子迁移skills.0002，确保新环境可直接加载三项技能。专项11/11、全量166/166通过，迁移一致性、Django check和diff check通过，停在T031。

- 2026-09-05：完成T029。新增SkillManager，支持运行时BaseSkill注册与重复保护、已启用Skill按项目/全局范围加载、明确触发词匹配、稳定评分排序和1-10条推荐上限；专项9/9、全量164/164通过，迁移一致性、Django check和diff check通过，停在T030。

- 2026-09-05：流程复核发现T028开发前未按AGENTS与CONTRACT_ENFORCEMENT完整输出标准会话启动审计和确认格式；功能代码与测试不受影响，但流程门禁记录不完整。本次已暂停后续开发并补读契约，后续任务严格执行“审计反馈→用户确认→编码→两轮测试→标准完成报告→暂停等待确认”。

- 2026-09-05：完成T028。新增skills app、项目/全局范围的版本化Skill模型、触发条件/能力/工具/知识/输入输出契约字段、启停状态与唯一约束，新增抽象BaseSkill运行时基类并接入Django Admin；应用skills.0001迁移。专项4/4、全量159/159通过，迁移一致性、Django check和diff check通过，停在T029。

- 2026-09-05：完成T115。工作台新增“知识库”入口和页面，接入知识库/文档/QA/检索真实接口；支持创建和编辑知识库、上传TXT/Markdown/PDF/DOCX、解析、向量化、审核、问答添加与审核、检索结果展示，并提供加载、空数据、401/403、失败重试和处理中反馈。前端生产构建通过；5173知识库路由和API资源HTTP 200，使用platform_admin真实登录后知识库列表与检索代理调用成功（当前无数据返回空列表），停在T028。
- 2026-09-05：补充T115空数据引导；无知识库时页面明确说明先创建知识库后即可使用上传、解析、向量化、问答和审核入口，并保留右上角“新建知识库”操作，前端构建复核通过。

- 2026-09-05：完成T027。新增知识库、文档、问答和检索REST接口，支持安全文件上传、解析、向量化、审核和项目成员隔离；响应不暴露文档存储路径，检索仅返回活动知识库中已解析且已通过审核的内容。专项24/24、全量155/155通过；迁移无待应用、makemigrations检查无变化、Django check和diff check通过。8000端口三个知识接口未认证访问均按预期返回401，停在T115前端闭环。

- 2026-09-05：完成T026。文档新增审核状态/备注/审核人/时间，新增review_asset服务，管理员或具备项目管理权限的测试负责人可执行通过、拒绝、暂缓；未解析文档不可通过，待审核不可重置，内容和审核记录分离。检索只返回活动知识库中已解析且已通过文档或已通过问答，审核结果进入时间与人员审计。迁移knowledge.0002、专项20/20及全量151/151通过，停在T027。

- 2026-09-05：完成T025。新增knowledge.retrieval，使用可替换Vectorizer协议和离线HashVectorizer生成确定性向量，向量化ready文档分块并记录模型/维度；余弦检索限制Top-K/阈值，过滤非active知识库、未解析文档和未审核Q&A，支持知识库范围筛选，未调用真实模型。专项15/15、全量146/146通过，停在T026。

- 2026-09-05：完成T024。新增knowledge.loader，按允许根目录和10MB上限读取TXT/Markdown/PDF/DOCX，UTF-8 BOM/换行规范化，500字符/50重叠分块，幂等替换Embedding分块并维护Document解析状态；解析失败状态独立提交，错误信息脱敏。新增pypdf5.9.0、python-docx1.1.2及lxml依赖。专项10/10和全量141/141通过，停在T025。

- 2026-09-05：完成T023。新增knowledge app与四类模型：项目/共享知识库、来源文档、问答对、向量分块；知识库分类和文档解析状态、QA审核状态均有严格枚举与校验，项目/来源边界受模型级验证。向量以严格数字数组落地，T025再接pgvector；应用knowledge.0001迁移、注册Admin。
- 文档加载（T024）：KNOWLEDGE_DOCUMENT_ROOT默认为.backend/.runtime/knowledge-documents，最大10MB；KNOWLEDGE_CHUNK_SIZE默认为500、OVERLAP为50。load_and_chunk仅写Embedding内容和来源元数据，不生成向量。专项5/5与全量136/136通过，停在T024。

- 2026-09-05：用户继续后完成T022。新增environments.check_all_health Celery任务，遍历所有环境、跳过未配置检查地址、隔离单环境异常并返回checked/healthy/unhealthy/skipped/errors汇总；beat每300秒调度。第一轮专项28/28、第二轮全量131/131及实际eager delay通过，停在决策者验收。

- 2026-09-05：用户继续后完成T021；实现授权管理员/测试负责人手动健康检查，页面展示结果/时间/耗时，2xx健康、网络/超时/非2xx异常并自动更新可用状态，维护状态保留。新增允许目标origin配置，默认仅http://127.0.0.1:8000，不跟随重定向/不携带凭据/不使用环境代理。地址修改清除旧结果，过期结果返回409。完成两轮测试后停在T022前。

- 2026-09-05：完成T096待页面验收；工作台新增环境管理入口，支持项目切换、四类型环境创建/编辑/删除、环境/健康状态、配置存在标记、保留/替换/清空凭据。只读权限、空项目引导、输入错误、403、503重试、401过期均通过浏览器验证。健康检查未接入，页面明确说明，停在T021前。

- 2026-09-05：完成T020，新增/api/environments/ CRUD与project筛选。管理员可管理全部环境；测试负责人需项目owner/manager角色才能写入，其他项目成员只读。凭据配置只写、响应仅返回存在标记，省略保留、空对象清空；禁止跨项目转移或伪造健康状态。真实代理联调及两轮验证通过，停在T096前。

- 2026-09-05：用户要求继续开发新任务，完成T019。新增项目级四类型环境模型、唯一约束、可用状态与独立健康状态、HTTP地址校验和配置加密字段；应用本地迁移并注册内部Admin。两轮测试通过，停在T020前。前序T114页面开发与修复已完成，未将自动化验证记为用户逐项页面验收。

- 2026-09-04：完成T114待决策者验收；AITS工作台新增“项目与智能体”入口，支持项目CRUD、成员候选与角色管理、智能体创建/新版本编辑/历史/回滚/删除，并补齐安全配置选项契约；真实代理链路和100项全量回归通过，停在页面验收前。
- 2026-09-04：完成T018；实现项目隔离的智能体CRUD、编辑生成新版本、历史查询、回滚生成新版本及整条版本链删除，补齐项目角色权限并防止越权名称探测；真实代理链路及全量回归通过，停在T114前等待确认。
- 2026-09-04：完成T017；新增`agents` app与项目级版本化`Agent`模型，建立项目、模型配置、提示词配置关联，并为尚未落地的知识库和Skills保留严格校验的引用列表；迁移、Admin和两轮测试通过，停在T018开始前等待确认。
- 2026-09-04：完成T016；项目REST API已支持项目CRUD、创建者自动成为owner、成员列表/添加/改权/移除及平台管理员与项目角色分层权限。两轮测试和真实代理链路通过，停在T017开始前等待确认。
- 2026-09-04：决策者验收T113后完成T015；创建`projects` app、UUID项目边界和四级项目成员关系，应用本地迁移并接入Django Admin，停在T016开始前等待确认。
- 2026-09-04：完成T113开发；工作台新增“提示词配置”入口，完成四级筛选、创建/编辑、变量预览、版本历史、回滚和删除的真实API联调，停在决策者页面验收前。
- 2026-09-04：修复T126验收问题；JWT登录成功后写入`last_login`，当前旧会话无历史值时显示“当前会话在线”；管理员在存在另一名启用管理员时可修改本人角色，最后一名管理员仍受锁死保护，停在再次验收和T113前。
- 2026-09-04：完成T014；实现管理员提示词CRUD、安全预览、不可变版本历史和回滚生成新版本，真实代理链路已验证，停在T113前端闭环开始前等待确认。
- 2026-09-04：完成T013；新增11类内置场景提示词与幂等数据迁移，新环境自动预置且不覆盖本地编辑；全量回归发现并修复旧提示词测试受种子数据污染的问题，停在T014开始前等待确认。
- 2026-09-04：修复用户权限页面新增后Vite热更新缓存错误；文件本身及生产构建无误，冷重启前端开发服务后`/`、`/src/styles/index.css`和`/workspace/users`均恢复HTTP 200。
- 2026-09-04：决策者确认V5.3批量任务治理规则；一次性确认5个或以上任务时，编码前全量严格审查所有既有功能，批量中每5个任务执行兼容性审查、全量测试、Git提交和附注标签；规则已同步核心契约、会话续接、启动审计和任务清单。
- 2026-09-04：完成T126补漏；新增管理员用户列表及角色/账号状态管理API、工作台“用户权限”入口和真实API联调，加入管理员自我降级/停用保护，停在用户验收和T013前。
- 2026-09-04：用户再次确认开发记忆：后端业务功能完成后必须紧接对应前端和真实API联调，确保控制者与决策者可从工作台操作验收；规则已固化到`AGENTS.md`、会话审计和本状态文件。
- 2026-09-04：完成T012；实现全局→项目→场景→即时的提示词合并、最新有效版本选择、变量优先级覆盖、项目名称隔离和内置安全默认降级，停在T013开始前等待用户确认。
- 2026-09-04：按用户反馈完成全局视觉升级；登录/注册、工作台和模型配置页统一为深空青紫科技风，新增轨道核心、极光、网格、玻璃卡片及低干扰动效，不改变业务流程。
- 2026-09-04：完成T011；新增四级作用域、11类场景、模板变量、版本及启用状态的数据模型，应用本地迁移并接入Django Admin，停在T012开始前等待用户确认。
- 2026-09-04：完成继续开发前审计及 T005A 补漏；按约定停在 T006 开始前，等待用户确认。
- 2026-09-04：按用户反馈修正注册流程；用户名或邮箱任选其一即可注册，登录入口同时支持两种账号。
- 2026-09-04：完成 T006；按 PRD 建立五角色操作矩阵与对象作用域门禁，停在 T007 开始前等待确认。
- 2026-09-04：完成 T007；新增模型配置数据结构并应用本地迁移，停在 T008 开始前等待确认。
- 2026-09-04：完成 T008；API Key 使用独立环境密钥进行 Fernet 加密，停在 T009 开始前等待确认。
- 2026-09-04：完成 T009；实现配置加载、任务类型路由、模型切换、实例缓存和按优先级自动故障降级，停在 T010 开始前等待确认。
- 2026-09-04：完成 T010；实现管理员模型配置 CRUD、安全连接测试入口及持久化用量统计，停在 T011 开始前等待确认。
- 2026-09-04：用户确认V5.2纵向交付规则；后续每个业务模块按“后端→前端→真实API联调→用户验收”闭环。当前优先执行T097模型配置页面，验收后再进入T011。
- 2026-09-04：完成T097；工作台新增管理员模型配置入口，完成CRUD、密钥轮换、连接测试、用量统计、默认模型及状态反馈的真实API联调，停在用户页面验收和T011前。
- 2026-09-04：修复T097前端热更新样式路径异常；确认 `frontend/src/styles/model-config.css` 存在并重启前端开发服务，冷启动构建与页面HTTP检查通过。
- 2026-09-04：完成本地验收账号准备；新增 `platform_admin`（业务角色`admin`、Django staff），仅用于本地验收，密码不写入项目文件，首次登录后必须修改。
- 2026-09-04：归档角色授予流程；新注册用户固定为`viewer`，管理员通过 Django Admin 的 User/Profile 编辑页授予 `test_leader`、`tester`、`developer` 或 `viewer`，平台管理员权限只由现有管理员授予，不开放自助提权。
- 2026-09-04：归档本日开发；T001-T010、T097及相关补漏完成，V5.1/V5.2四份基线文档已确认，下一次Codex CLI会话按本文件和`AGENTS.md`先启动服务、审计后从T011继续。
- T002 远程联调已在腾讯云独立 `aits_v5` 环境完成：PostgreSQL 16、pgvector、Redis 7、Celery Worker/Beat 与 Django 后端均已验证。
- 2026-09-03：用户确认本次开发结束。
- 下次用户发送“开始”或“继续”时：先运行 `start-dev.cmd`，检查 5173/8000 服务，完整读取并审计四份基线文档，再从 T011（或用户指定的补漏任务）继续；严格执行“后端→前端→真实API联调→用户验收”闭环。
- 正式用户入口：`http://127.0.0.1:5173/`
- 内部管理入口：`http://127.0.0.1:8000/admin/`

## 最近验证

- T026 第一轮：审核专项20/20通过，覆盖文档/QA通过、拒绝、暂缓、审核人时间备注、未解析禁止通过、viewer/跨项目拒绝、Q&A检索门禁。修复旧T025夹具以明确文档审核状态，修复审核异常类型与换行写入问题。
- T026 第二轮：迁移knowledge.0002应用成功；后端全量151/151、迁移一致性与Django检查通过。

- T025 第一轮：检索专项15/15通过，覆盖向量化前置条件、确定性向量和元数据、项目隔离、知识库/文档状态、Q&A审核门禁、排序/阈值/Top-K边界；修复Q&A向量被文档状态过滤的条件组合问题。
- T025 第二轮：后端全量146/146、迁移一致性、Django检查和git diff检查通过，无新增迁移。

- T024 第一轮：文档解析专项10/10通过，覆盖TXT/Markdown规范化、PDF/DOCX提取、分块边界/重叠、幂等替换、路径越界、大小限制、空文档、不支持扩展名、二进制编码和失败状态持久化；修复blank/事务回滚导致失败状态未保存。
- T024 第二轮：后端全量141/141、迁移一致性、Django检查和git diff检查通过；无新迁移，前端未改动。

- T023 第一轮：知识模型专项5/5通过，覆盖分类/项目范围、文档来源与解析状态、QA审核人/来源库边界、Embedding单一来源/向量校验/分块唯一性、JSON元数据及级联删除。首次发现Django blank向量跳过校验，已在Embedding.clean显式补齐。
- T023 第二轮：迁移knowledge.0001应用成功；后端全量136/136、迁移一致性与Django检查通过。

- T022 第一轮：Celery专项28/28通过，覆盖5分钟beat注册、空扫描、目标更新、单项失败隔离、eager执行。
- T022 第二轮：后端全量131/131、迁移一致性和Django检查通过；Django正常初始化后实际delay执行返回空环境汇总，beat任务名environments.check_all_health、间隔300秒。

- T021 第一轮：环境专项24/24通过（新增9项检查器测试），涵盖HTTP成功/错误/重定向、超时、网络异常脱敏、origin边界、空地址、维护状态、401/403/404、配置编辑/较新检查结果冲突409与只读结果字段。前端生产构建通过。
- T021 第二轮：迁移environments.0002应用成功；Edge浏览器经5173真实代理调用本地8000健康接口，验证200成功→404异常→恢复、结果时间持久化及维护状态保留；临时项目/环境清理。后端全量127/127、迁移一致性与Django检查通过。未访问外部目标。

- T096 第一轮：前端生产构建通过，EnvironmentView页面与路由/API/导航生成成功。
- T096 第二轮：Edge无界面浏览器经真实5173代理完成管理员登录→创建临时项目→页面创建环境→非法JSON反馈→编辑保留凭据→清空配置→删除；验证403保存失败、503刷新重试、遮罩关闭、390px无横向溢出。真实viewer注册登录验证无项目引导与加入项目后只读，模拟401/刷新失败验证过期提示。临时项目、环境和只读用户已清理；后端全量118/118、迁移一致性、Django检查通过；环境页面与健康接口HTTP 200。

- T020 第一轮：环境模型/API专项15/15通过（API新增8项），覆盖CRUD、五角色权限、项目管理门禁、跨项目404、匿名401、非法输入/重复400、凭据不回显及错误密钥503。
- T020 第二轮：经5173真实代理完成登录→创建项目/环境→列表/详情→PATCH→PUT保留凭据→空对象清空→删除，临时数据已清理；后端全量118/118、Django system check及迁移一致性检查通过，无新增迁移或依赖，前后端HTTP 200。

- T019 第一轮：模型专项7/7通过，覆盖四类型、项目唯一性、非法状态/地址/JSON、加密落库与ORM更新、错误密钥、维护状态独立及级联删除。
- T019 第二轮：本地迁移environments.0001_initial成功；Shell在事务内创建dev/test/staging/prod并验证配置解密，临时数据已回滚；后端全量110/110、Django检查与迁移一致性检查通过，前后端HTTP 200。

- 2026-09-05 提示词刷新反馈验收修复：刷新按钮增加旋转指示、正在刷新文案和请求期间禁用；成功显示通知及持久的刷新时间/当前配置数，失败显示错误通知和重试提示。第一轮前端生产构建通过；第二轮 Edge 浏览器经真实登录验证真实刷新、请求等待状态、单次请求、模拟503反馈及真实重试恢复，全部通过，未修改提示词数据。

- 2026-09-05 模型配置弹窗验收修复：使用 Teleport 将模型页弹窗挂载到 body，避免主内容层级低于固定侧栏导致遮罩无法接收点击；遮罩使用 click.self，表单内点击保持打开。第一轮前端生产构建通过；第二轮 Edge 无界面浏览器经真实登录验证编辑框输入不关闭、左右遮罩关闭、×关闭及添加框遮罩关闭，全部通过，未保存或修改模型数据。T114仍待决策者验收，下一任务仍为T019。

- T114 第一轮：前端生产构建通过；项目/智能体页面、API封装、路由和全员工作台入口生成成功；后端页面契约与智能体专项测试9/9通过，并补齐安全成员候选列表及智能体`project_id`响应
- T114 第二轮：经5173真实AITS代理完成管理员登录→创建项目→选择候选用户→添加manager→读取无密钥配置选项→创建智能体v1→编辑v2→历史查询→回滚v3，临时项目/用户/Mock模型已清理；后端全量回归100/100、前端生产构建、Django system check及迁移一致性检查通过；根页面、项目页面与后端HTTP 200
- T114 验收修复：确认 `frontend/src/styles/index.css` 使用同目录 `./project-agent.css` 导入，前端生产构建通过；重启开发服务后入口可用，避免旧进程缓存已删除的 `frontend/project-agent.css` 路径。
- T114 二次验收修复：新增管理员安全目录接口 `/api/configs/models/catalog/`；模型配置表单启动时加载供应商、支持类型与推荐模型，供应商/类型变化时联动刷新建议，支持 datalist 自定义模型名；后端配置/项目/智能体专项68/68、system check与前端构建通过，并经真实API验证目录返回。
- T114 三项验收修复：模型“测试连接”接入通用 `/models` 探测器并安全返回鉴权/网络错误；添加模型弹窗支持点击遮罩关闭；工作台左侧导航改为固定定位、主内容独立偏移滚动；配置专项43/43与前端构建通过。
- T114 视觉验收修复：修正固定侧栏与 CSS Grid 叠加造成的主内容窄列，工作台改为固定侧栏 + 全宽内容流；模型名称改为真正下拉选择；按 DeepSeek 官方当前目录补齐 `deepseek-v4-flash`、`deepseek-v4-pro` 与视觉实验模型 `deepseek-v4-flash-vision-exp`；前端构建及配置专项43/43复测通过。
- V5.3审查复核：后端全量回归95/95、Django system check通过、迁移一致性检查通过、前端生产构建通过，5173提示词/模型页面HTTP 200；当前仍未创建Git检查点或推送，等待决策者确认审查处置方案。
- V5.3整改复核：后端全量回归98/98（含连接适配器专项3项）、Django system check通过、迁移一致性检查通过、前端生产构建通过；连接测试对成功、401、缺失地址均有自动化覆盖。本机沙箱出站连接返回WinError 10013，已明确记录为运行环境网络限制；沙箱外访问DeepSeek `/models` 可达并返回401，证明接口路径可用。当前未推送远程，等待决策者验收。
- T018 第一轮：智能体API专项测试7/7通过；修正重复名称模型异常为标准400，并将项目写权限检查前移，防止非成员借重复校验探测项目内资源名称
- T018 第二轮：经5173真实代理完成登录→创建v1→编辑v2→历史查询→回滚生成v3→删除版本链，临时数据已清理；后端全量回归98/98、Django system check及迁移一致性检查通过；前后端HTTP 200
- T017 第一轮：智能体模型专项测试5/5通过；首次测试发现Django会对`blank=True`的空列表跳过字段验证，新增模型级强制JSON结构校验后复测通过
- T017 第二轮：Shell创建完整项目级智能体配置并验证project/model/prompt/knowledge/skills/version/status关联后清理临时数据；后端全量回归91/91、Django system check及迁移一致性检查通过；前后端HTTP 200
- T016 第一轮：项目API专项测试7/7通过；首次测试发现创建响应缺少`member_count`，修正序列化后复测通过，覆盖所有者自动建立、可见范围、成员管理、角色写权限、所有者保护及401/404边界
- T016 第二轮：经5173真实代理完成登录→创建项目→自动owner→添加成员→查询成员→状态更新→删除，临时数据已清理；后端全量回归86/86、Django system check及迁移一致性检查通过；前后端HTTP 200
- T005 专项测试：6/6 通过
- 后端全量回归：16/16 通过
- Django system check：通过
- 迁移一致性检查：无待生成迁移
- 前端访问：`http://127.0.0.1:5173/`，HTTP 200
- 后端健康检查：`http://127.0.0.1:8000/`，HTTP 200
- 匿名访问当前用户接口：`/api/auth/me/`，HTTP 401
- T005A 第一轮：前端生产构建通过
- T005A 第二轮：经 5173 代理完成健康检查→注册→登录→当前用户完整链路
- T005A 补漏第一轮：前端生产构建通过；认证状态登录/退出响应式检查通过
- T005A 补漏第二轮：配置独立 API 基址时，401→刷新 Token→携带新 Token 重试链路通过
- 补漏后回归：后端全量测试 16/16 通过；Django system check 通过；无待生成迁移
- 补漏后运行检查：前端 HTTP 200；后端 `/api/health/` HTTP 200
- T002 远程补漏：业务数据库原缺少 pgvector 扩展，已创建并验证 `vector=0.8.6`
- T002 远程第一轮：PostgreSQL 16.15 查询成功；Redis `PONG`；Django system check 通过；后端健康接口 HTTP 200
- T002 远程第二轮：Celery Worker `pong`；通过 Redis Broker 执行 `health_probe` 并成功返回；Celery Beat 正常运行
- T002 远程容器状态：backend/worker/beat/redis/db 全部运行，Redis 与 PostgreSQL 健康，重启次数均为 0
- T002 持久化补漏：Compose 固定项目名 `aits_v5` 并挂载 pgvector 初始化脚本；全新临时数据库验证可自动启用 `vector=0.8.6`
- 前端构建补漏：Element Plus 改为按需注册，主 JS 包由约 1.06 MB 降至约 236 kB，Vite 大包警告已消除
- 全部补漏后回归：后端 16/16 通过；前端生产构建通过；本地前后端 HTTP 200；远程 V5 服务 HTTP 200
- 注册流程补漏第一轮：认证专项测试 10/10 通过，覆盖用户名注册、邮箱注册、邮箱登录、旧账号兼容、重复校验和错误密码
- 注册流程补漏第二轮：后端全量测试 20/20 通过且无警告；经 5173 代理完成用户名注册链路和邮箱注册链路；前端生产构建通过
- T006 第一轮：权限矩阵专项测试 7/7 通过
- T006 第二轮：后端全量回归 27/27 通过；Django system check 通过；无待生成迁移；前后端 HTTP 200
- T007 第一轮：模型专项测试 4/4 通过；迁移定义一致
- T007 第二轮：本地迁移应用成功；Shell 创建/排序/查询多个模型配置通过；后端全量回归 31/31 通过；前后端 HTTP 200
- T008 第一轮：加密专项测试 5/5 通过，覆盖密文落库、解密、明文拦截、空值、错误密钥及无效配置
- T008 第二轮：后端全量回归 36/36 通过；依赖检查通过；无待生成迁移；前后端 HTTP 200
- T009 第一轮：模型管理器专项测试 8/8 通过，覆盖加载、默认排序、能力路由、切换、单次指定、缓存与故障降级
- T009 第二轮：后端全量回归 44/44 通过；Django system check 通过；无待生成迁移；前端与后端健康接口 HTTP 200
- T010 第一轮：模型配置 API 专项测试 6/6 通过，覆盖 CRUD、密钥保护、默认切换、权限、连接适配与用量统计
- T010 第二轮：本地迁移 `configs.0002_modelusagerecord` 应用成功；后端全量回归 50/50 通过；Django system check 通过；无待生成迁移；前后端 HTTP 200；未认证模型接口返回 401
- T097 第一轮：前端生产构建通过；模型配置页面及独立路由成功生成，主包约239.47 kB、页面异步包约11.72 kB
- T097 第二轮：真实本地JWT链路完成模型创建→列表→用量→删除，响应不含密钥字段；后端全量回归50/50、system check及迁移检查通过；前端最终生产构建通过；模型路由与前后端健康检查HTTP 200
- T097 补漏验证：修复CSS资源解析错误后，前端服务冷启动成功；`npm run build`通过；`http://127.0.0.1:5173/` HTTP 200
- T011 第一轮：提示词模型专项测试 4/4 通过，覆盖四级作用域、默认值、模板变量校验、版本共存和重复版本约束
- T011 第二轮：本地迁移 `configs.0003_promptconfig_promptconfig_config_prompt_version_uniq` 应用成功；后端全量回归 54/54 通过；Django system check 通过；无待生成迁移；前后端 HTTP 200
- 全局视觉升级验证：前端生产构建通过；登录页和工作台路由 HTTP 200；动画遵循系统“减少动态效果”设置
- T012 第一轮：提示词管理器专项测试 7/7 通过，覆盖四级合并、优先级、版本选择、项目隔离、变量覆盖、默认降级和非法场景
- T012 第二轮：后端全量回归 61/61 通过；Django system check 通过；无待生成迁移；前后端 HTTP 200
- T126 第一轮：用户管理API专项测试 4/4 通过，覆盖安全列表、角色与账号状态更新、401/403及管理员自我锁死保护；前端生产构建通过
- T126 第二轮：经5173真实代理完成管理员登录→用户列表→角色调整，临时数据已清理；后端全量回归65/65、system check和迁移检查通过；用户管理页面及后端健康接口HTTP 200
- T013 第一轮：默认提示词专项测试4/4通过，覆盖11场景完整性、内容与变量有效性、幂等初始化、不覆盖本地编辑及管理器合并
- T013 第二轮：首次全量回归发现T011/T012旧测试未隔离迁移种子数据，修复隔离后后端全量回归69/69通过；system check和迁移一致性检查通过；本地11条默认提示词覆盖11个场景；前后端HTTP 200
- T014 第一轮：提示词API专项测试5/5通过，覆盖CRUD、版本历史、回滚、模板变量预览、非法版本及401/403
- T014 第二轮：经5173真实代理完成创建v1→编辑v2→历史查询→变量预览→回滚v3，临时数据已清理；后端全量回归74/74、system check和迁移检查通过；前后端HTTP 200
- T126验收修复：认证与用户权限专项测试15/15、后端全量回归75/75、前端生产构建、system check和迁移检查通过；经5173真实代理验证登录时间已记录且保留另一管理员时本人可由admin改为test_leader，临时账号已清理
- T113 第一轮：前端生产构建通过；提示词页面、API模块、管理员路由和工作台入口成功生成
- T113 第二轮：经5173真实代理读取11条默认提示词并完成创建v1→编辑v2→预览→历史→回滚v3，临时数据已清理；后端全量回归75/75、system check和迁移检查通过；根页面、CSS、提示词页面及后端健康接口HTTP 200
- T015 第一轮：项目模型专项测试4/4通过，覆盖项目默认值与JSON设置、成员角色、项目内成员唯一性及非法字段校验；本地迁移`projects.0001_initial`应用成功
- T015 第二轮：后端全量回归79/79通过；Django system check和迁移一致性检查通过；前后端HTTP 200
- Django Admin 静态资源：HTTP 200，开发启动脚本已修复
- 角色授予验收：`platform_admin` 业务角色为`admin`；Django Admin `/admin/` HTTP 200；模型配置入口按角色显示

## 开发环境

- 向量检索（T025）：`vectorize_document(document, vectorizer)`只处理Document.ready的Embedding分块并记录model_name；默认HashVectorizer为本地离线64维hash向量，仅用于开发/测试。`retrieve(query, knowledge_base_ids, top_k<=50, threshold)`使用余弦排序，默认只返回active知识库、ready文档或approved问答的向量；当前向量列为JSON数组，后续可替换pgvector适配，不提供API。

- 健康检查（T021）：POST /api/environments/{uuid}/health-check/，沿用环境管理权限；结果字段health_checked_at/health_message/health_latency_ms只读。允许目标由ENVIRONMENT_HEALTH_ALLOWED_ORIGINS配置（逗号分隔的scheme+host+port），默认http://127.0.0.1:8000；配置写入部署环境并重启后端后生效。.env.example为样例，不由开发启动脚本自动加载。仅检查health_check_url，未填写返回400；2秒连接/3秒读取超时，响应只读状态码。定时任务尚未启用，验收地址可用http://127.0.0.1:8000/api/health/。

- 环境前端（T096）：/workspace/environments，所有登录用户可从侧栏进入，管理员或具备项目owner/manager的测试负责人可管理；其他项目成员只读。配置输入为完整JSON对象，编辑默认保留，替换/清空需显式选择；不读取现有凭据。验收使用platform_admin，先在项目与智能体创建项目，再在环境管理选择项目完成操作。

- 环境API（T020）：/api/environments/与/api/environments/{uuid}/；支持?project={uuid}。database_config/auth_config/variables仅写入；has_database_config/has_auth_config/has_variables用于展示配置状态，can_manage表示当前管理权限。健康状态仅供读取，未实现健康探测或测试执行审批。写入按事务锁定当前行以保留省略配置，异常统一返回400/403/404/503。

- 环境模型（T019）：Environment按project+name唯一，name为dev/test/staging/prod；默认unavailable/unknown，维护状态与健康状态独立。database_config/auth_config/variables使用EncryptedObjectField，对Python提供字典、数据库JSON列存Fernet密文字符串；复用MODEL_CONFIG_FERNET_KEY，无新依赖，禁止对加密配置使用JSON键查询，需读取环境后访问。Admin仅管理元数据，不回显配置凭据。T020已实现API，产品页面T096已完成待验收。

- Python：项目根目录 `.venv`
- OCR：Python Pillow 11.3.0 + pytesseract 0.3.13；Windows Tesseract OCR 5.5.3，本地解析器通过 `TESSERACT_CMD` 或默认安装路径发现引擎
- Django settings：`config.settings.dev`
- 本地数据库：SQLite
- Celery：memory broker + eager 模式
- JWT：djangorestframework-simplejwt 5.5.1
- 加密：cryptography 50.0.1（Fernet）；独立密钥变量 `MODEL_CONFIG_FERNET_KEY`
- 模型管理：`core.llm.ModelManager`；具体 Provider 运行时通过工厂注入，外部调用测试使用 Fake/Mock
- 模型配置 API：`/api/configs/models/`；仅管理员可访问，`api_key` 只写且密文永不通过 API 返回
- 模型连接测试：Provider 适配器未注册时安全返回 503；测试仅使用 Fake，不调用真实外部模型
- 模型用量：`ModelUsageRecord` 持久化输入/输出 Token、费用及成功状态，详情动作提供聚合统计
- 模型配置前端：`/workspace/models`；仅平台`admin`角色显示入口并允许访问，其他角色安全返回工作台
- 提示词配置模型：`PromptConfig`；支持`global/project/scene/instant`四级作用域、11类场景、JSON模板变量和版本唯一约束
- 提示词管理：`core.prompts.PromptManager`；按全局→项目→场景→即时合并，高优先级变量覆盖低优先级变量，无配置时返回内置安全默认提示词
- 默认提示词：`core.prompts.defaults`与`configs.0004_seed_default_prompts`；预置全局、需求分析、用例生成、用例评审、接口、AI、UI、APP、性能、截图识别和报告生成11类场景，重复初始化不覆盖本地修改
- 提示词配置API：`/api/configs/prompts/`；仅管理员可访问，编辑创建不可变新版本，提供`history`、`preview`和`rollback`动作，回滚以新版本保留审计历史
- 提示词配置前端：`/workspace/prompts`；仅管理员显示入口并允许访问，支持层级/场景筛选、创建编辑、JSON变量预览、版本历史、回滚和删除反馈
- 项目模型：`Project`使用UUID主键并作为后续资产隔离边界；`ProjectMember`支持owner/manager/member/viewer项目角色，同一用户在同一项目中唯一
- 项目 REST API：`/api/projects/`；登录用户可创建项目并自动成为owner，普通用户仅能查看所属项目，owner/manager可管理成员，平台管理员可管理全部项目，owner成员关系禁止通过成员接口篡改或移除
- 智能体模型：`Agent`按项目隔离并支持名称+版本唯一约束，关联模型与提示词配置，包含知识库/技能引用、运行参数、类型、状态和创建人审计；知识库与Skills实体落地前使用严格校验的字符串ID列表
- 智能体 REST API：`/api/agents/`；默认列表仅返回各智能体最新版本，支持项目筛选、完整历史、不可变新版本编辑、指定版本回滚和版本链删除；owner/manager可编辑，成员只读，删除限owner或平台管理员
- 项目与智能体前端：`/workspace/projects`；所有登录用户可从AITS侧栏进入，按项目角色呈现只读或管理操作，覆盖项目、成员、智能体及版本管理的加载、空依赖、错误和权限状态；Django Admin不属于正式客户操作流程
- 用户权限管理：`/api/auth/users/`与`/workspace/users`；仅平台管理员可访问，可修改其他用户角色和启用状态，禁止管理员降级或停用自己
- 本地Fernet密钥：`start-dev.ps1`首次启动时随机生成到被Git忽略的`.runtime/model-config-fernet.key`并在后续启动复用
- 前端：Vue 3 + Vite，端口 5173
- 后端：Django，端口 8000

 - 2026-09-06：T131安装工作台中文与来源切换补漏。第三方 Skill 安装页面统一中文来源、状态、权限、操作、加载和错误文案；来源类型从本地文件切换到远程来源时自动清理残留 `local://` 地址并恢复对应示例地址。前端生产构建通过，待浏览器验收来源切换和完整生命周期操作。

 - 2026-09-06：执行验收项1/2。通过真实 Chrome CDP 登录后访问 `/workspace/requirements`、`/workspace/case-generation`、`/workspace/skill-installations`、`/workspace/skill-audits` 和 `/workspace/skills`，页面入口、中文标题、加载/空数据状态和代理请求均通过，未发现英文旧标签或替换字符；切换到含记录项目后，评审与自动化筛选按钮在已完成状态均正确禁用，重复 REST 调用幂等返回200且约4ms。专项35/35、后端全量278/278、前端生产构建通过；DeepSeek连接测试200，但当前唯一激活配置为 `model_type=chat`，没有可执行视觉模型，因此截图语义模型真实验收待配置视觉模型后继续，当前保留确定性 OCR/人工确认降级。

- 2026-09-06：本轮整改验收已归档。T047-L、T094、T095、T049、T131 的代码、REST、前端入口、真实代理联调和重复操作验证均完成；视觉模型语义结果因当前仅激活 chat 模型延期到用户配置视觉模型后单独验收，不影响已完成的安全降级链路和本轮归档。

- 2026-09-09：T146 模型发现错误分层补漏完成。`ModelConfigViewSet` 保持 DRF 参数校验 400；新增模型凭据加密配置缺失/解密失败的明确 503 响应，覆盖模型发现和模型保存入口，未使用吞掉未知异常的 `except Exception`；新增缺失 Fernet 密钥回归测试。专项 22/22、后端全量 323/323、Django system check 通过；目标服务器发现原远程 AI 补丁造成 `views.py` 语法错误并导致 backend 退出，已用本地通过测试的代码恢复；目标部署补入持久化 `MODEL_CONFIG_FERNET_KEY`（原数据库无模型及加密凭据，先备份 `.env.remote`），backend/worker/beat 重建运行，健康接口 HTTP 200。经目标服务器 `:8090` 真实代理登录 HTTP 200；非法供应商发现返回 400；测试凭据的供应商发现返回脱敏 503 而非 500，响应不回显凭据。当前浏览器自动化表面不可用，页面级验收需用户在浏览器刷新后继续确认；未推送 Git。

## 关键约定

- 每次新会话先运行根目录的 `start-dev.cmd`。
- 每个任务完成后进行两轮测试并暂停，等待用户确认。
- 自动化测试中的外部调用使用 Mock，禁止无授权真实计费；模型连接测试和目标部署最终验收的单次真实短调用例外，须遵守 T145/T146 的明确授权、无业务数据和不自动重试规则。
- 本文件是跨会话进度的唯一摘要入口；完成任务后必须同步更新。
- 新会话必须按 `SESSION_START_AUDIT.md` 审计 TASKS、PRD、技术架构、测试证据和实际实现；报告无遗漏或遗漏项并取得用户确认后，方可继续编码。
- 后端模型/服务可以按依赖逐项开发，但 REST API 完成后下一任务必须是对应前端页面、真实 API 联调和决策者验收；没有可操作的工作台入口，不得把业务模块标记为闭环完成或进入下一业务模块。
- 决策者一次性确认5个或以上任务时，编码前触发全部既有功能的人类使用逻辑、社会认知、需求和安全严格审查；发现问题先报告并暂停。
- 批量开发每累计完成5个任务，必须完成Git变更与新旧兼容性审查、专项及全量测试、前端构建和关键端到端验证，然后创建Git提交及`checkpoint/YYYYMMDD-任务范围`附注标签并报告；无可信基线时先创建`baseline/YYYYMMDD-pre-batch`，任何回滚仍须决策者明确授权。
