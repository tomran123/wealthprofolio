from fastapi import APIRouter

from app.api.routes import (
    accounts,
    agent,
    auth,
    data_management,
    documents,
    exposure_groups,
    fx_rates,
    holdings,
    institutions,
    instruments,
    jobs,
    knowledge,
    llm_providers,
    owners,
    portfolio,
    settings,
    transactions,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agent.router)
api_router.include_router(agent.jobs_router)
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
api_router.include_router(transactions.router)
api_router.include_router(llm_providers.router)
api_router.include_router(documents.router)
api_router.include_router(knowledge.router)
api_router.include_router(jobs.router)
