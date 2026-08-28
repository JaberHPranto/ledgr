from fastapi import APIRouter

from backend.app.api.routes import home
from backend.app.api.routes.auth import (
    activate,
    login,
    logout,
    password_reset,
    refresh,
    register,
)
from backend.app.api.routes.bank_account import activate as bank_account_activate
from backend.app.api.routes.bank_account import create as bank_account_create
from backend.app.api.routes.bank_account import (
    deposit,
    transaction_history,
    transfer,
    withdraw,
)
from backend.app.api.routes.next_of_kin import all as next_of_kin_all
from backend.app.api.routes.next_of_kin import create as next_of_kin_create
from backend.app.api.routes.next_of_kin import delete as next_of_kin_delete
from backend.app.api.routes.next_of_kin import update as next_of_kin_update
from backend.app.api.routes.profile import all_profiles, create, me, update, upload

api_router = APIRouter()

api_router.include_router(home.router)

api_router.include_router(register.router)
api_router.include_router(activate.router)
api_router.include_router(login.router)
api_router.include_router(password_reset.router)
api_router.include_router(refresh.router)
api_router.include_router(logout.router)

api_router.include_router(create.router)
api_router.include_router(update.router)
api_router.include_router(upload.router)
api_router.include_router(me.router)
api_router.include_router(all_profiles.router)

api_router.include_router(next_of_kin_create.router)
api_router.include_router(next_of_kin_update.router)
api_router.include_router(next_of_kin_delete.router)
api_router.include_router(next_of_kin_all.router)

api_router.include_router(bank_account_create.router)
api_router.include_router(bank_account_activate.router)
api_router.include_router(deposit.router)
api_router.include_router(transfer.router)
api_router.include_router(withdraw.router)
api_router.include_router(transaction_history.router)
