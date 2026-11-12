"""Test environment for PAGA MULTI-AI: every model switched on with dummy keys and state-changing writes enabled,
so scenario tests exercise the real routing, guard and player routes. Real keys are never used in tests."""
import os
from unittest.mock import patch

ENV={'PAGA_GEMINI_ENABLED':'true','PAGA_GROQ_ENABLED':'true','PAGA_QWEN_ENABLED':'true','PAGA_AUTONOMOUS_WRITES_ENABLED':'true',
     'GEMINI_API_KEY':'test-gemini-key-0000','GROQ_API_KEY':'test-groq-key-0000','PAGA_GEMINI_MODEL':'','PAGA_GROQ_MODEL':''}


def start(**overrides):
    """Patch os.environ; returns the patcher (call .stop() in tearDown)."""
    values={**ENV,**overrides}
    patcher=patch.dict(os.environ,{key:value for key,value in values.items() if value is not None})
    patcher.start()
    for key,value in values.items():
        if value is None:os.environ.pop(key,None)
    return patcher


def models(model):
    """Patches routing every model lane (API clients and the local Qwen) to the same scripted test model."""
    return (patch('game.qwen_runtime.generate',side_effect=model),
            patch('game.paga_ai_providers.remote_generate',side_effect=lambda provider,messages,**kwargs:model(messages,**kwargs)))
