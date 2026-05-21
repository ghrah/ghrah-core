# SPDX-FileCopyrightText: 2026 chenxya <chenxya@ghrah.org>
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from ghrah.communication.supervisor import SupervisorActor
from ghrah.core.server.config import CoreServerConfig
from ghrah.core.server.connection_manager import ConnectionManager
from ghrah.core.server.event_bus import EventBus
from ghrah.core.server.router import MessageRouter
from ghrah.core.server.server import WebSocketServer

logger = logging.getLogger(__name__)


def create_app(config: CoreServerConfig | None = None) -> FastAPI:
    if config is None:
        config = CoreServerConfig()

    connection_manager = ConnectionManager()
    event_bus = EventBus(connection_manager)

    supervisor: SupervisorActor | None = None
    router: MessageRouter | None = None
    ws_server: WebSocketServer | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal supervisor, router, ws_server

        logging.basicConfig(
            level=getattr(logging, config.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        logger.info("Starting ghrah-core server...")

        supervisor = SupervisorActor()
        logger.info("SupervisorActor initialized")

        router = MessageRouter(
            supervisor=supervisor,
            connection_manager=connection_manager,
            event_bus=event_bus,
            ability_timeout=config.ability_timeout,
        )

        # 注入 CommandSender（Router）和 EventBus 到 Supervisor
        supervisor._command_sender = router
        supervisor._event_bus = event_bus

        ws_server = WebSocketServer(config, connection_manager, router, event_bus)

        await event_bus.start()
        logger.info("EventBus started")

        yield

        logger.info("Shutting down ghrah-core server...")
        await event_bus.stop()
        if router is not None:
            router.cancel_pending_requests()
        logger.info("Core server shutdown complete")

    app = FastAPI(
        title="ghrah-core",
        description="ghrah system Core server - WebSocket data plane for Subject connections",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.websocket(config.ws_path)
    async def websocket_endpoint(websocket: WebSocket):
        await ws_server.handle_connection(websocket)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "active_sessions": connection_manager.connection_count,
        }

    @app.get("/")
    async def root():
        return {
            "name": "ghrah-core",
            "version": "0.1.0",
            "description": "Core server - WebSocket data plane for Subject connections",
        }

    return app


def main() -> None:
    import uvicorn

    config = CoreServerConfig.from_env()
    app = create_app(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        ws_ping_interval=config.ping_interval,
        ws_ping_timeout=config.ping_timeout,
    )


if __name__ == "__main__":
    main()
