"""Administrator-only model configuration REST endpoints."""

from decimal import Decimal
from dataclasses import asdict
from django.shortcuts import get_object_or_404
import re

from django.db import transaction
from django.db.models import Count, DecimalField, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.configs.models import ModelConfig, ModelRoutingPolicy, PromptConfig
from apps.configs.serializers import (ModelConfigSerializer, ModelRoutingPolicySerializer, PromptConfigSerializer, ModelDiscoverySerializer, ConnectionModeSerializer, SafeModelSummarySerializer)
from apps.configs.catalog import provider_catalog
from apps.configs.routing import ModelRouteError, ModelRouteResolver, required_model_types
from apps.configs.services import ConnectionTester, ProviderConnectionTester, ProviderError, discover_models, canonical_base
from apps.users.permissions import IsAdminRole




class ModelConfigViewSet(viewsets.ModelViewSet):
    """Manage model configurations without ever returning encrypted secrets."""

    queryset = ModelConfig.objects.all()
    serializer_class = ModelConfigSerializer
    permission_classes = (IsAdminRole,)
    connection_tester: ConnectionTester = ProviderConnectionTester()

    @action(detail=False, methods=("get",))
    def catalog(self, request: Request) -> Response:
        """Return safe provider/type/model suggestions for the configuration form."""
        return Response({"providers": provider_catalog()})

    @action(detail=False, methods=("post",))
    def discover(self, request: Request) -> Response:
        """Discover a draft model endpoint without persisting or returning secrets."""
        serializer = ModelDiscoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = ModelConfig(provider=data["provider"], api_base_url=data["api_base_url"])
        try:
            if data.get("api_key"):
                config.set_api_key(data["api_key"])
            elif data.get("config_id"):
                saved = get_object_or_404(self.get_queryset(), pk=data["config_id"])
                if saved.provider != config.provider or canonical_base(saved.provider, saved.api_base_url) != canonical_base(config.provider, config.api_base_url):
                    return Response({"api_key": ["地址或供应商已变化，请重新填写密钥后同步。"]}, status=400)
                config.api_key_encrypted = saved.api_key_encrypted
            return Response(discover_models(config, data["cursor"]))
        except ProviderError as exc:
            return Response({"message": str(exc), "code": exc.code, "complete": False}, status=503)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return Response({"message": "供应商目录响应格式异常。", "code": "invalid_response", "complete": False}, status=503)

    @action(detail=True, methods=("post",), url_path="test-connection")
    def test_connection(self, request: Request, pk: str | None = None) -> Response:
        config = self.get_object()
        mode_serializer = ConnectionModeSerializer(data=request.data)
        mode_serializer.is_valid(raise_exception=True)
        mode = mode_serializer.validated_data["mode"]
        result = self.connection_tester.test(config) if mode == "catalog" else self.connection_tester.test(config, mode=mode)
        response_status = status.HTTP_200_OK if result.ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(
            asdict(result),
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


class ModelRoutingPolicyViewSet(viewsets.ModelViewSet):
    """Manage global and feature model route policies for administrators."""

    queryset = ModelRoutingPolicy.objects.select_related("primary_model", "backup_model").all()
    serializer_class = ModelRoutingPolicySerializer
    permission_classes = (IsAdminRole,)

    def get_queryset(self):
        """Return policies in stable feature order."""
        return self.queryset.order_by("feature_key")

    @action(detail=False, methods=("get",))
    def matrix(self, request: Request) -> Response:
        """Return every routable feature, options, and its effective model."""
        resolver = ModelRouteResolver()
        policies = {
            policy.feature_key: policy
            for policy in self.get_queryset()
        }
        rows: list[dict[str, object]] = []
        for feature_key, feature_label in ModelRoutingPolicy.FeatureKey.choices:
            policy = policies.get(feature_key)
            required = required_model_types(feature_key)
            available_query = ModelConfig.objects.filter(is_active=True)
            if feature_key != ModelRoutingPolicy.FeatureKey.GLOBAL:
                available_query = available_query.filter(model_type__in=required)
            available = SafeModelSummarySerializer(
                available_query.order_by("priority", "name"), many=True
            ).data
            try:
                route = resolver.resolve(feature_key)
                effective = route.primary.config if route.primary else None
                effective_source = route.primary.source if route.primary else ""
                route_error = ""
            except ModelRouteError as exc:
                effective = None
                effective_source = ""
                route_error = str(exc)
            policy_data = self.get_serializer(policy).data if policy else {
                "id": None,
                "feature_key": feature_key,
                "feature_label": feature_label,
                "primary_model_id": None,
                "primary_model": None,
                "backup_model_id": None,
                "backup_model": None,
                "allow_fallback": False,
                "allow_deterministic_baseline": False,
                "is_active": True,
            }
            rows.append({
                **policy_data,
                "required_model_types": list(required),
                "available_models": available,
                "inherits_global": feature_key != ModelRoutingPolicy.FeatureKey.GLOBAL and not policy_data["primary_model_id"],
                "effective_model": SafeModelSummarySerializer(effective).data if effective else None,
                "effective_source": effective_source,
                "route_error": route_error,
            })
        return Response(rows)

    @action(detail=False, methods=("post",))
    @transaction.atomic
    def upsert(self, request: Request) -> Response:
        """Create or update one feature policy without requiring a client-side ID."""
        feature_key = request.data.get("feature_key")
        if not feature_key:
            return Response({"feature_key": ["必须选择功能。"]}, status=status.HTTP_400_BAD_REQUEST)
        policy = ModelRoutingPolicy.objects.filter(feature_key=feature_key).first()
        serializer = self.get_serializer(policy, data=request.data, partial=policy is not None)
        serializer.is_valid(raise_exception=True)
        saved = serializer.save()
        return Response(
            self.get_serializer(saved).data,
            status=status.HTTP_200_OK if policy else status.HTTP_201_CREATED,
        )


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
