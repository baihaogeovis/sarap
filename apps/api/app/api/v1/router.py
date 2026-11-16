from fastapi import APIRouter

from app.api.v1 import (
    areas,
    assets,
    auth,
    briefings,
    catalog,
    internal,
    products,
    projects,
    scenes,
    service_accounts,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(areas.router)
api_router.include_router(scenes.router)
api_router.include_router(catalog.router)
api_router.include_router(assets.router)
api_router.include_router(tasks.router)
api_router.include_router(products.router)
api_router.include_router(briefings.router)
api_router.include_router(service_accounts.router)
api_router.include_router(internal.router)
