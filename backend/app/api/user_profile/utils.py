from datetime import date

from fastapi import HTTPException


def validate_id_dates(issue_date: date, expiry_date: date):
    if issue_date >= expiry_date:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "Issue date cannot be after expiry date",
            },
        )
