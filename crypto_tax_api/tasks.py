# Create tasks.py
import logging

from celery import shared_task

from crypto_tax_api.models import ExchangeCredential
from crypto_tax_api.services.exchange_services import ExchangeServiceFactory

logger = logging.getLogger(__name__)

@shared_task
def sync_exchange_task(credential_id, force_full_sync=False, start_date=None, end_date=None):
    try:
        credential = ExchangeCredential.objects.get(id=credential_id)
        service = ExchangeServiceFactory.get_service(credential.exchange, credential.user)

        # This now runs in background
        return service.sync_transactions(
            start_date=start_date,
            end_date=end_date,
            force_full_sync=force_full_sync
        )
    except Exception as e:
        logger.error(f"Background sync failed: {str(e)}")
        raise