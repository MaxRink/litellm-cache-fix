"""Regression tests for embedding inputs through the async offload boundary."""

import ast
import asyncio
import sys
import types
from collections.abc import Sequence
from types import MappingProxyType
from pathlib import Path


def _load_methods(litellm):
    source = (Path(__file__).parents[2] / "litellm" / "router.py").read_text()
    tree = ast.parse(source)
    wanted = {"_acount_pre_call_check_tokens", "_count_pre_call_check_tokens"}
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]

    class Logger:
        def error(self, *_args, **_kwargs):
            raise AssertionError("token precheck unexpectedly failed")

    def offload_token_count(fn):
        async def run(*args, **kwargs):
            return fn(*args, **kwargs)
        return run

    namespace = {
        "Sequence": Sequence,
        "cast": lambda _type, value: value,
        "litellm": litellm,
        "verbose_router_logger": Logger(),
        "offload_token_count": offload_token_count,
        "MappingProxyType": MappingProxyType,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "router.py", "exec"), namespace)
    return namespace


def test_embedding_inputs_are_counted_without_responses_transformer():
    class FakeLiteLLM:
        @staticmethod
        def token_counter(**kwargs):
            return len(kwargs.get("text", ""))

    methods = _load_methods(FakeLiteLLM())
    # Stub only the optional system-message normalizer imported by the method;
    # this keeps the test independent of the full provider dependency graph.
    module_name = "litellm.llms.anthropic.pass_through.messages.utils"
    module = types.ModuleType(module_name)
    module.anthropic_system_to_openai_message = lambda _system: None
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module

    class FakeRouter:
        _acount_pre_call_check_tokens = methods["_acount_pre_call_check_tokens"]
        _count_pre_call_check_tokens = methods["_count_pre_call_check_tokens"]

        def _pre_call_checks_need_token_count(self, model, healthy_deployments):
            return True

    async def run():
        router = FakeRouter()
        cases = (("one embedding", 13), (["one", "two"], 6), ([1, 2, 3], 3), ([[1, 2], [3]], 3))
        for input_value, expected in cases:
            result = await router._acount_pre_call_check_tokens(
                model="embedding-model", healthy_deployments=[{}], messages=None,
                input=input_value, request_kwargs=None,
            )
            assert result == expected

        # A Responses-shaped item still takes the existing transformer path;
        # this asserts the patch did not reinterpret structured input as tokens.
        result = methods["_count_pre_call_check_tokens"](
                router, [{"type": "input_text", "text": "hello"}], None, None
        )
        assert result == 0

        responses_param = types.ModuleType("openai.types.responses.response_create_params")
        responses_param.ResponseInputParam = list
        transform_mod = types.ModuleType("litellm.responses.litellm_completion_transformation.transformation")
        class ResponsesConfig:
            @staticmethod
            def transform_responses_api_input_to_messages(*, input, responses_api_request):
                assert input == [{"type": "input_text", "text": "structured"}]
                return [{"role": "user", "content": "structured"}]
        transform_mod.LiteLLMCompletionResponsesConfig = ResponsesConfig
        previous_modules = {name: sys.modules.get(name) for name in ("openai.types.responses.response_create_params", "litellm.responses.litellm_completion_transformation.transformation")}
        sys.modules.update({
            "openai.types.responses.response_create_params": responses_param,
            "litellm.responses.litellm_completion_transformation.transformation": transform_mod,
        })
        try:
            result = methods["_count_pre_call_check_tokens"](
                router, None, [{"type": "input_text", "text": "structured"}], None
            )
            assert result == 0
        finally:
            for name, previous_module in previous_modules.items():
                if previous_module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous_module

    try:
        asyncio.run(run())
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
