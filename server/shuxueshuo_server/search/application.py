"""Shared single-process search startup, maintenance, and shutdown lifecycle."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from .dev_api import create_search_router
from .repository import SearchRepository

LOGGER = logging.getLogger(__name__)
CLEANUP_INTERVAL = 60


async def maintain_search(repository, stopped):
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=CLEANUP_INTERVAL)
        except TimeoutError:
            try:
                await run_in_threadpool(repository.cleanup)
            except Exception:
                LOGGER.exception("Search cleanup will retry")


def install_search(app, *, settings=None):
    @asynccontextmanager
    async def lifespan(app):
        product = app.state.product
        configured = settings or product.settings
        repository = SearchRepository(product.db, configured.root / "work/search/private-v1")
        app.state.search_repository = repository
        app.state.search_drain_path = configured.root / "locks/services-draining"
        app.state.search_accepting = False
        await run_in_threadpool(repository.recover)
        await run_in_threadpool(repository.cleanup)
        stopped = asyncio.Event()
        cleaner = asyncio.create_task(maintain_search(repository, stopped))
        app.state.search_accepting = True
        try:
            yield
        finally:
            app.state.search_accepting = False
            stopped.set()
            await cleaner

    app.include_router(APIRouter(lifespan=lifespan))
    app.include_router(create_search_router(None))
