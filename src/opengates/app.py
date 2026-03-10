from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .gates import GateLoader
from .providers import build_provider
from .runtime import GateRuntime
from .schemas import ApiSubmissionRequest, ApiThreadCreateRequest, ApiThreadReplyRequest
from .settings import get_settings
from .storage import LocalStore


def create_app() -> FastAPI:
    settings = get_settings()
    gate_loader = GateLoader(settings.gates_dir)
    store = LocalStore(settings.data_dir)
    runtime = GateRuntime(gate_loader=gate_loader, store=store, provider=build_provider(settings))

    app = FastAPI(title="OpenGates OSS MVP")
    templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        gates = []
        for gate_id in gate_loader.list_gates():
            bundle = gate_loader.load(gate_id)
            gates.append({"gate_id": gate_id, "title": bundle.title, "public_path": bundle.public_path})
        return templates.TemplateResponse(request, "index.html", {"gates": gates})

    @app.get("/demo", response_class=HTMLResponse)
    def demo_gate(request: Request) -> HTMLResponse:
        return gate_intake(request, "demo-investor")

    @app.get("/g/{gate_id}", response_class=HTMLResponse)
    def gate_intake(request: Request, gate_id: str) -> HTMLResponse:
        try:
            gate = gate_loader.load(gate_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(request, "intake.html", {"gate": gate})

    @app.post("/g/{gate_id}/threads")
    def create_thread_form(
        gate_id: str,
        name: str = Form(""),
        email: str = Form(""),
        content: str = Form(...),
        priority_paid: str | None = Form(None),
    ) -> RedirectResponse:
        try:
            processed = runtime.start_thread(
                gate_id,
                name=name,
                email=email,
                content=content,
                payment_status="paid" if priority_paid else "none",
                source="web_thread",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url=f"/t/{processed.thread.thread_id}", status_code=303)

    @app.post("/g/{gate_id}/submit")
    def submit_form_alias(
        gate_id: str,
        name: str = Form(""),
        email: str = Form(""),
        content: str = Form(...),
        priority_paid: str | None = Form(None),
    ) -> RedirectResponse:
        return create_thread_form(
            gate_id=gate_id,
            name=name,
            email=email,
            content=content,
            priority_paid=priority_paid,
        )

    @app.get("/t/{thread_id}", response_class=HTMLResponse)
    def thread_view(request: Request, thread_id: str) -> HTMLResponse:
        try:
            view = runtime.get_thread_view(thread_id)
            gate = gate_loader.load(view.thread.gate_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        closed = view.thread.status in {"declined", "escalated", "expired", "review"}
        return templates.TemplateResponse(
            request,
            "thread.html",
            {"gate": gate, "thread_view": view, "thread_closed": closed},
        )

    @app.post("/t/{thread_id}/reply")
    def reply_to_thread_form(thread_id: str, content: str = Form(...)) -> RedirectResponse:
        try:
            runtime.reply_to_thread(thread_id, content=content, source="web_thread")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=f"/t/{thread_id}", status_code=303)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/gates")
    def list_gates() -> dict:
        return {"gates": gate_loader.list_gates()}

    @app.post("/api/gates/{gate_id}/threads")
    def api_create_thread(gate_id: str, payload: ApiThreadCreateRequest) -> dict:
        try:
            processed = runtime.start_thread(
                gate_id,
                name=payload.name,
                email=payload.email,
                content=payload.content,
                payment_status=payload.payment_status,
                source="api",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return processed.model_dump(mode="json")

    @app.post("/api/gates/{gate_id}/submit")
    def api_submit_alias(gate_id: str, payload: ApiSubmissionRequest) -> dict:
        return api_create_thread(gate_id, payload)

    @app.get("/api/threads/{thread_id}")
    def api_get_thread(thread_id: str) -> dict:
        try:
            view = runtime.get_thread_view(thread_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return view.model_dump(mode="json")

    @app.post("/api/threads/{thread_id}/reply")
    def api_reply_to_thread(thread_id: str, payload: ApiThreadReplyRequest) -> dict:
        try:
            processed = runtime.reply_to_thread(
                thread_id,
                content=payload.content,
                payment_status=payload.payment_status,
                source="api",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return processed.model_dump(mode="json")

    @app.get("/api/logs/recent")
    def recent_logs(limit: int = 20) -> dict:
        return {"events": store.recent_events(limit=limit)}

    return app


app = create_app()
