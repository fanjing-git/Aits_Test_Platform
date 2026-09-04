"""Built-in prompt templates installed for every platform environment."""

from __future__ import annotations

from dataclasses import dataclass

from apps.configs.models import PromptConfig


@dataclass(frozen=True)
class DefaultPromptTemplate:
    name: str
    scene_type: str
    content: str
    variables: dict[str, object]
    scope: str = PromptConfig.Scope.SCENE


DEFAULT_PROMPTS = (
    DefaultPromptTemplate(
        name="platform-default",
        scope=PromptConfig.Scope.GLOBAL,
        scene_type=PromptConfig.SceneType.DEFAULT,
        content=(
            "你是AI智能体测试平台的质量工程助手。先理解用户目标、角色和约束，再给出准确、可验证且可执行的结果。"
            "明确区分事实、推断和待确认项；不得编造测试结果、绕过权限或暴露敏感信息。"
        ),
        variables={"language": "zh-CN", "tone": "professional"},
    ),
    DefaultPromptTemplate(
        name="requirement-analysis-default",
        scene_type=PromptConfig.SceneType.REQUIREMENT_ANALYSIS,
        content=(
            "分析需求时识别参与角色、业务目标、正常流程、边界、异常、安全、权限和跨模块联动。"
            "输出功能拆解、歧义与风险、可测试验收条件及需求到测试点的映射；信息不足时明确提出待确认问题。"
        ),
        variables={"include_risks": True, "include_acceptance_criteria": True},
    ),
    DefaultPromptTemplate(
        name="case-generation-default",
        scene_type=PromptConfig.SceneType.CASE_GEN,
        content=(
            "基于已确认需求生成可执行测试用例，覆盖正常、边界、异常、安全、权限、兼容性和数据一致性。"
            "每条用例包含标题、前置条件、步骤、输入、预期结果、优先级、类型和需求映射；避免重复及不可验证描述。"
        ),
        variables={"priorities": ["P0", "P1", "P2", "P3"]},
    ),
    DefaultPromptTemplate(
        name="case-review-default",
        scene_type=PromptConfig.SceneType.CASE_REVIEW,
        content=(
            "从需求覆盖、步骤可执行性、预期可验证性、数据独立性、边界异常、安全权限和重复度评审测试用例。"
            "指出具体缺口与影响，给出可直接修改的建议，并保留评审依据和需求映射。"
        ),
        variables={"require_evidence": True},
    ),
    DefaultPromptTemplate(
        name="api-test-default",
        scene_type=PromptConfig.SceneType.API_TEST,
        content=(
            "按pytest规范设计接口测试，覆盖请求契约、响应结构、状态码、认证授权、幂等、超时、重试和业务数据流转。"
            "优先采用数据驱动和可复用fixture；隔离外部服务并使用Mock，禁止产生真实计费或破坏生产数据。"
        ),
        variables={"framework": "pytest", "external_calls": "mock"},
    ),
    DefaultPromptTemplate(
        name="ai-test-default",
        scene_type=PromptConfig.SceneType.AI_TEST,
        content=(
            "从准确性、相关性、完整性、一致性、安全性、鲁棒性、公平性和可解释性八个维度评估被测AI。"
            "使用可复现输入、明确评分标准和证据，覆盖提示词注入、越权、敏感信息泄露及多轮上下文风险。"
        ),
        variables={"dimensions": 8},
    ),
    DefaultPromptTemplate(
        name="ui-test-default",
        scene_type=PromptConfig.SceneType.UI_TEST,
        content=(
            "使用Playwright、pytest和Page Object Model生成稳定的UI测试。"
            "优先使用语义定位，覆盖加载、空数据、成功、失败、无权限和响应式状态；测试数据与页面对象分离，失败时保留截图和上下文。"
        ),
        variables={"framework": "playwright", "pattern": "POM"},
    ),
    DefaultPromptTemplate(
        name="app-test-default",
        scene_type=PromptConfig.SceneType.APP_TEST,
        content=(
            "使用Appium设计APP测试，明确平台、设备、系统版本、应用版本和前置状态。"
            "覆盖安装升级、权限、前后台切换、网络变化、手势、兼容性、日志和性能指标，并确保设备操作可恢复。"
        ),
        variables={"framework": "appium"},
    ),
    DefaultPromptTemplate(
        name="performance-test-default",
        scene_type=PromptConfig.SceneType.PERF_TEST,
        content=(
            "根据现有资产和场景在JMeter与Locust之间选择合适引擎，定义负载模型、并发、持续时间、数据隔离和停止条件。"
            "报告P50/P90/P99、吞吐量、错误率和资源瓶颈；压测生产环境或可能影响他人前必须获得明确审批。"
        ),
        variables={"default_engine": "locust"},
    ),
    DefaultPromptTemplate(
        name="screenshot-analysis-default",
        scene_type=PromptConfig.SceneType.SCREENSHOT_ANALYSIS,
        content=(
            "分析截图时区分直接可见事实和推断，识别布局、文字、控件、状态、遮挡、对齐、对比度与异常提示。"
            "使用清晰位置描述并保护个人及敏感信息；无法从图像确认的内容不得臆测。"
        ),
        variables={"distinguish_inference": True},
    ),
    DefaultPromptTemplate(
        name="report-generation-default",
        scene_type=PromptConfig.SceneType.REPORT_GEN,
        content=(
            "生成结构清晰、面向决策者的测试报告，先给出结论，再呈现范围、环境、结果、失败证据、风险、覆盖度和建议。"
            "区分已验证事实与推断，保留需求—测试点—用例映射；不得隐藏失败、夸大质量或泄露敏感数据。"
        ),
        variables={"audience": "decision-maker"},
    ),
)


def install_default_prompts() -> tuple[PromptConfig, ...]:
    """Install missing version-one defaults without overwriting local edits."""
    installed: list[PromptConfig] = []
    for template in DEFAULT_PROMPTS:
        prompt, _ = PromptConfig.objects.get_or_create(
            name=template.name,
            scope=template.scope,
            scene_type=template.scene_type,
            version=1,
            defaults={
                "content": template.content,
                "variables": template.variables,
                "is_active": True,
            },
        )
        installed.append(prompt)
    return tuple(installed)
