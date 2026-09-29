from fastapi import APIRouter

from app.api.v1.routers import (
    admin, agents, analytics, applications, assessments, auth, candidates, interviews, jobs, offers, onboarding,
    organizations, portal, public, requisitions,
)

api_router = APIRouter()
for module in (auth, organizations, requisitions, jobs, candidates, applications, assessments, interviews, offers,
               onboarding, analytics, agents, admin, portal, public):
    api_router.include_router(module.router)
