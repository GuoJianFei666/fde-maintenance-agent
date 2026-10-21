"""Expose the new demo's REST API; start locally with one worker."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from react_agent.config import Settings
from react_agent.models import (
    AlarmEvent,
    Approval,
    ConflictError,
    MissingModelConfig,
    ModelCallError,
    NotFoundError,
)
from react_agent.service import AgentService


def create_app(settings: Settings | None = None, model=None):
    config = settings or Settings.from_env()
    service = AgentService(config, model=model)

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(title="设备告警处置 Agent", version="0.1.0", lifespan=lifespan,
                  description="个人FDE演示项目：Agent工具调用、检索、人工确认与本地工单写入。数据为构造样例。")
    app.state.service = service

    @app.exception_handler(NotFoundError)
    async def missing(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(MissingModelConfig)
    async def unconfigured(request: Request, exc: MissingModelConfig):
        return JSONResponse(status_code=503, content={"error": "model_not_configured"})

    @app.exception_handler(ModelCallError)
    async def provider_error(request: Request, exc: ModelCallError):
        return JSONResponse(status_code=502, content={"error": "model_call_failed", "category": str(exc)})

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["状态"])
    def health():
        return {"status": "ok", "model_configured": bool(config.api_key), "model": config.model,
                "execution_mode": service.model.mode, "data_kind": "synthetic_demo"}

    @app.get("/api/devices", tags=["演示业务数据"])
    def devices():
        return service.store.devices()

    @app.get("/api/devices/{device_id}", tags=["演示业务数据"])
    def device(device_id: str):
        return service.store.device(device_id)

    @app.get("/api/manuals/search", tags=["演示业务数据"])
    def manuals(device_id: str, q: str = Query(min_length=2, max_length=160),
                top_k: int = Query(default=3, ge=1, le=5)):
        return service.store.search(q, device_id, top_k)

    @app.get("/api/work-orders", tags=["演示业务数据"])
    def orders(device_id: str | None = None):
        return service.store.orders(device_id)

    @app.post("/api/alarms", tags=["Agent工作流"])
    def diagnose(alarm: AlarmEvent):
        return service.diagnose(alarm)

    @app.get("/api/runs/{run_id}", tags=["Agent工作流"])
    def run(run_id: str):
        return service.store.run(run_id)

    @app.get("/api/runs/{run_id}/trace", tags=["交付记录"])
    def trace(run_id: str):
        return service.store.traces(run_id)

    @app.post("/api/runs/{run_id}/approval", tags=["Agent工作流"])
    def decide(run_id: str, decision: Approval):
        return service.decide(run_id, decision)

    @app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse, tags=["交付记录"])
    def report(run_id: str):
        return PlainTextResponse(service.report_markdown(run_id), media_type="text/markdown")

    return app
