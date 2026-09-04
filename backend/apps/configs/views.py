"""Administrator-only model configuration REST endpoints."""

from decimal import Decimal
import re

from django.db import transaction
from django.db.models import Count, DecimalField, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.configs.models import ModelConfig, PromptConfig
from apps.configs.serializers import ModelConfigSerializer, PromptConfigSerializer
from apps.configs.services import ConnectionTester, UnavailableConnectionTester
from apps.users.permissions import IsAdminRole


MODEL_CATALOG = {
    "openai": {
        "label": "OpenAI",
        "types": {
            "chat": {"label": "对话模型", "models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-4o-mini"]},
            "embedding": {"label": "向量模型", "models": ["text-embedding-3-small", "text-embedding-3-large"]},
            "vision": {"label": "视觉模型", "models": ["gpt-4o", "gpt-4.1"]},
        },
    },
    "anthropic": {"label": "Anthropic", "types": {"chat": {"label": "对话模型", "models": ["claude-sonnet-4-5", "claude-haiku-4-5"]}, "vision": {"label": "视觉模型", "models": ["claude-sonnet-4-5"]}}},
    "google": {"label": "Google Gemini", "types": {"chat": {"label": "对话模型", "models": ["gemini-2.5-pro", "gemini-2.5-flash"]}, "embedding": {"label": "向量模型", "models": ["text-embedding-005"]}, "vision": {"label": "视觉模型", "models": ["gemini-2.5-pro", "gemini-2.5-flash"]}}},
    "qwen": {"label": "通义千问", "types": {"chat": {"label": "对话模型", "models": ["qwen-plus", "qwen-max", "qwen-turbo"]}, "embedding": {"label": "向量模型", "models": ["text-embedding-v3"]}, "vision": {"label": "视觉模型", "models": ["qwen-vl-max"]}}},
    "baidu": {"label": "文心一言", "types": {"chat": {"label": "对话模型", "models": ["ernie-4.5-turbo-32k", "ernie-speed-128k"]}, "embedding": {"label": "向量模型", "models": ["embedding-v1"]}, "vision": {"label": "视觉模型", "models": ["ernie-4.5-turbo-vl"]}}},
    "deepseek": {"label": "DeepSeek", "types": {"chat": {"label": "对话模型", "models": ["deepseek-chat", "deepseek-reasoner"]}}},
    "zhipu": {"label": "智谱", "types": {"chat": {"label": "对话模型", "models": ["glm-4.5", "glm-4.5-air"]}, "vision": {"label": "视觉模型", "models": ["glm-4.1v-thinking-flash"]}}},
    "azure": {"label": "Azure OpenAI", "types": {"chat": {"label": "对话模型", "models": []}, "embedding": {"label": "向量模型", "models": []}, "vision": {"label": "视觉模型", "models": []}}},
    "custom": {"label": "OpenAI 兼容", "types": {"chat": {"label": "对话模型", "models": []}, "embedding": {"label": "向量模型", "models": []}, "vision": {"label": "视觉模型", "models": []}}},
    "local": {"label": "Ollama / vLLM", "types": {"chat": {"label": "对话模型", "models": ["llama3.1", "qwen2.5"]}, "embedding": {"label": "向量模型", "models": ["nomic-embed-text"]}, "vision": {"label": "视觉模型", "models": ["llava"]}}},
}


class ModelConfigViewSet(viewsets.ModelViewSet):
    """Manage model configurations without ever returning encrypted secrets."""

    queryset = ModelConfig.objects.all()
    serializer_class = ModelConfigSerializer
    permission_classes = (IsAdminRole,)
    connection_tester: ConnectionTester = UnavailableConnectionTester()

    @action(detail=False, methods=("get",))
    def catalog(self, request: Request) -> Response:
        """Return safe provider/type/model suggestions for the configuration form."""
        providers = [
            {"value": value, "label": item["label"], "types": [
                {"value": type_value, "label": type_item["label"], "models": type_item["models"]}
                for type_value, type_item in item["types"].items()
            ]}
            for value, item in MODEL_CATALOG.items()
        ]
        return Response({"providers": providers})

    @action(detail=True, methods=("post",), url_path="test-connection")
    def test_connection(self, request: Request, pk: str | None = None) -> Response:
        config = self.get_object()
        result = self.connection_tester.test(config)
        response_status = status.HTTP_200_OK if result.ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(
            {
                "ok": result.ok,
                "message": result.message,
                "latency_ms": result.latency_ms,
            },
            status=response_status,
        )

    @action(detail=True, methods=("get",))
    def usage(self, request: Request, pk: str | None = None) -> Response:
        config = self.get_object()
        totals = config.usage_records.aggregate(
            calls=Count("id"),
            successful_calls=Count("id", filter=Q(success=True)),
            input_tokens=Coalesce(Sum("input_tokens"), Value(0), output_field=IntegerField()),
            output_tokens=Coalesce(Sum("output_tokens"), Value(0), output_field=IntegerField()),
            cost=Coalesce(
                Sum("cost"),
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=18, decimal_places=8),
            ),
        )
        totals["failed_calls"] = totals["calls"] - totals["successful_calls"]
        totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
        totals["cost"] = str(totals["cost"])
        return Response({"model_config_id": config.pk, **totals})


class PromptConfigViewSet(viewsets.ModelViewSet):
    """Manage active prompts, immutable history, preview, and rollback."""

    serializer_class = PromptConfigSerializer
    permission_classes = (IsAdminRole,)
    queryset = PromptConfig.objects.all()

    def get_queryset(self):
        queryset = PromptConfig.objects.all()
        if self.action == "list":
            queryset = queryset.filter(is_active=True)
        scene_type = self.request.query_params.get("scene_type")
        scope = self.request.query_params.get("scope")
        if scene_type:
            queryset = queryset.filter(scene_type=scene_type)
        if scope:
            queryset = queryset.filter(scope=scope)
        return queryset.order_by("scope", "scene_type", "name", "-version")

    @action(detail=True, methods=("get",))
    def history(self, request: Request, pk: str | None = None) -> Response:
        config = self.get_object()
        versions = PromptConfig.objects.filter(
            name=config.name,
            scope=config.scope,
            scene_type=config.scene_type,
        ).order_by("-version")
        return Response(self.get_serializer(versions, many=True).data)

    @action(detail=True, methods=("post",))
    def preview(self, request: Request, pk: str | None = None) -> Response:
        config = self.get_object()
        supplied = request.data.get("variables", {})
        if not isinstance(supplied, dict):
            return Response(
                {"variables": ["必须是 JSON 对象。"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        variables = {**config.variables, **supplied}
        required = set(re.findall(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", config.content))
        missing = sorted(required - variables.keys())
        if missing:
            return Response(
                {"variables": [f"缺少模板变量：{', '.join(missing)}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rendered = re.sub(
            r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}",
            lambda match: str(variables[match.group(1)]),
            config.content,
        )
        return Response(
            {
                "prompt_config_id": config.pk,
                "version": config.version,
                "rendered_content": rendered,
                "variables": variables,
            }
        )

    @action(detail=True, methods=("post",))
    @transaction.atomic
    def rollback(self, request: Request, pk: str | None = None) -> Response:
        current = self.get_object()
        try:
            version = int(request.data.get("version"))
        except (TypeError, ValueError):
            return Response(
                {"version": ["请输入有效的历史版本号。"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        source = PromptConfig.objects.filter(
            name=current.name,
            scope=current.scope,
            scene_type=current.scene_type,
            version=version,
        ).first()
        if source is None:
            return Response(
                {"version": ["指定的历史版本不存在。"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(
            current,
            data={
                "content": source.content,
                "variables": source.variables,
                "is_active": True,
            },
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        restored = serializer.save()
        return Response(self.get_serializer(restored).data, status=status.HTTP_201_CREATED)
