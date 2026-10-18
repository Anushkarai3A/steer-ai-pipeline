from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.ids import new_id
from app.core.security import hash_password
from app.models import User, UserRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("steer")

API_PREFIX = "/api"


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.pipeline_version,
        description=(
            "Steer Research Studio — research paper to Instagram, with evidence traceability "
            "and a mandatory doctor approval gate."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.routes import (
        assets,
        auth,
        content,
        dashboard,
        evidence,
        pipeline,
        projects,
        publishing,
        review,
        settings as settings_routes,
    )

    for router in (
        auth.router, dashboard.router, projects.router, evidence.router,
        content.router, review.router, publishing.router, pipeline.router, assets.router,
        settings_routes.router,
    ):
        app.include_router(router, prefix="")

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
            errors.append({"field": loc or "body", "message": e.get("msg", "invalid value")})
        return JSONResponse(
            status_code=422,
            content={"detail": "Validation failed.", "code": "validation_error", "errors": errors},
        )

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.pipeline_version,
            "ai_enabled": settings.ai_enabled,
            "llm_provider": settings.llm_provider if settings.ai_enabled else "none",
            "database": "postgresql" if settings.database_url.startswith("postgres") else "sqlite",
        }

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        seed_users()
        repair_stranded_claims()
        logger.info("Steer backend ready (ai_enabled=%s)", settings.ai_enabled)

    return app


def seed_users() -> None:
    """Create demo accounts on first boot (credentials via environment)."""
    db: Session = SessionLocal()
    try:
        seeds = [
            (os.getenv("DEMO_EDITOR_EMAIL", "editor@steer.demo"),
             os.getenv("DEMO_EDITOR_PASSWORD", "demo1234"),
             os.getenv("DEMO_EDITOR_NAME", "Demo Editor"),
             UserRole.editor.value),
            (os.getenv("DEMO_DOCTOR_EMAIL", "doctor@steer.demo"),
             os.getenv("DEMO_DOCTOR_PASSWORD", "demo1234"),
             os.getenv("DEMO_DOCTOR_NAME", "Dr. Demo Reviewer"),
             UserRole.doctor.value),
            (os.getenv("DEMO_ADMIN_EMAIL", "admin@steer.demo"),
             os.getenv("DEMO_ADMIN_PASSWORD", "demo1234"),
             os.getenv("DEMO_ADMIN_NAME", "Demo Admin"),
             UserRole.admin.value),
        ]
        for email, password, name, role in seeds:
            if db.query(User).filter(User.email == email.lower()).first():
                continue
            db.add(User(
                id=new_id("usr"),
                email=email.lower(),
                name=name,
                role=role,
                password_hash=hash_password(password),
            ))
        db.commit()
    finally:
        db.close()


def repair_stranded_claims() -> None:
    """Reconcile claims stranded without evidence (old source-deletion cascade)."""
    from app.services.claims.evidence_link import repair_stranded_claims as repair

    db: Session = SessionLocal()
    try:
        repaired = repair(db)
        if repaired:
            logger.info(
                "Reconciled %d claim(s) stranded without evidence: %s",
                len(repaired), ", ".join(repaired),
            )
    finally:
        db.close()


app = create_app()
