from fastapi import APIRouter

from app.api.routes import (
    accounts,
    auth,
    data_management,
    exposure_groups,
    fx_rates,
    holdings,
    institutions,
    instruments,
    owners,
    portfolio,
    settings,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(owners.router)
api_router.include_router(institutions.router)
api_router.include_router(exposure_groups.router)
api_router.include_router(accounts.router)
api_router.include_router(instruments.router)
api_router.include_router(holdings.router)
api_router.include_router(fx_rates.router)
api_router.include_router(portfolio.router)
api_router.include_router(settings.router)
api_router.include_router(data_management.router)
