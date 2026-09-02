import json
import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.github.signature import verify_signature
from app.models import WebhookDelivery
from app.tasks.github_webhook import process_github_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, str]:
    settings = get_settings()
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(raw_body, signature_header, settings.github_webhook_secret):
        logger.warning("github webhook rejected: invalid or missing signature")
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"status": "invalid signature"}

    delivery_id = request.headers.get("X-GitHub-Delivery")
    event_type = request.headers.get("X-GitHub-Event")
    if not delivery_id or not event_type:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"status": "missing delivery headers"}

    try:
        payload = json.loads(raw_body)
    except ValueError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"status": "invalid payload"}

    installation = payload.get("installation") or {}
    delivery = WebhookDelivery(
        delivery_id=delivery_id,
        event_type=event_type,
        action=payload.get("action"),
        github_installation_id=installation.get("id"),
    )
    db.add(delivery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info(
            "github webhook duplicate delivery ignored",
            extra={"delivery_id": delivery_id, "event_type": event_type},
        )
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate ignored"}

    logger.info(
        "github webhook accepted",
        extra={"delivery_id": delivery_id, "event_type": event_type},
    )
    process_github_webhook.delay(delivery_id=delivery_id, event_type=event_type, payload=payload)
    return {"status": "accepted"}
