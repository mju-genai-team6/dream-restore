"""나레이션(TTS) import가 실패해도 실행기와 필수 핸들러는 남는지 확인한다. DB는 쓰지 않는다."""
import builtins
import importlib
import logging
import sys

import app.jobs as jobs_pkg
import app.jobs.handlers as handlers_pkg
import worker.image_gen as image_gen_pkg
import worker.render as render_pkg
from app.core.enums import JobType
from app.jobs import registry

_RELOADED = (
    "app.jobs.runner",
    "app.jobs.handlers.scenes",
    "app.jobs.handlers.images",
    "worker.image_gen.generate",
    "worker.render.handler",
    "worker.render.narration",
)


def test_narration_import_failure_keeps_required_handlers(monkeypatch, caplog):
    import app.jobs.runner as original_runner

    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        # import 문이 서브모듈 이름만 넘기거나, 패키지와 fromlist로 나눌 수 있다.
        if name == "worker.render.narration" or (name == "worker.render" and "narration" in fromlist):
            raise ImportError("No module named 'mutagen'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)

    saved_modules = {name: sys.modules.get(name) for name in _RELOADED}
    saved_handlers = dict(registry.HANDLERS)
    saved_success = dict(registry.ON_SUCCESS)
    saved_failure = dict(registry.ON_FAILURE)
    # on_success는 이미 있으면 import 중에 예외를 낸다. 필수 핸들러를 다시 등록하려면 비운다.
    registry.HANDLERS.clear()
    registry.ON_SUCCESS.clear()
    registry.ON_FAILURE.clear()
    for name in _RELOADED:
        sys.modules.pop(name, None)

    try:
        with caplog.at_level(logging.ERROR, logger="app.jobs.runner"):
            fresh = importlib.import_module("app.jobs.runner")
        assert fresh.get_handler(JobType.GENERATE_IMAGE) is not None
        assert fresh.get_handler(JobType.RENDER_VIDEO) is not None
        assert JobType.GENERATE_NARRATION not in registry.HANDLERS
        assert any("나레이션(TTS) 핸들러를 등록하지 못함" in record.message for record in caplog.records)
        assert any("mutagen" in record.message for record in caplog.records)
    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        jobs_pkg.runner = original_runner
        handlers_pkg.scenes = saved_modules["app.jobs.handlers.scenes"]
        handlers_pkg.images = saved_modules["app.jobs.handlers.images"]
        image_gen_pkg.generate = saved_modules["worker.image_gen.generate"]
        render_pkg.handler = saved_modules["worker.render.handler"]
        registry.HANDLERS.clear()
        registry.HANDLERS.update(saved_handlers)
        registry.ON_SUCCESS.clear()
        registry.ON_SUCCESS.update(saved_success)
        registry.ON_FAILURE.clear()
        registry.ON_FAILURE.update(saved_failure)
