from fastapi import APIRouter
from ..services.log_reader import parse_features_from_log

router = APIRouter(prefix="/api")


@router.get("/features")
def get_features():
    """Get latest feature values and resolution stats."""
    return parse_features_from_log()
