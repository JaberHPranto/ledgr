from app.core.logging import get_logger
from fastapi import APIRouter

router = APIRouter(prefix="/home")

logger = get_logger()


@router.get("")
async def root():
    return {"message": "Welcome to the Ledgr Backend API"}
