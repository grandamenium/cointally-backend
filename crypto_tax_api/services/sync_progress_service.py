# services/sync_progress_service.py
import time

from django.core.cache import cache
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging

logger = logging.getLogger(__name__)


class SyncProgressService:
    """
    Service for tracking and managing sync progress across multiple exchanges.
    Uses Redis/cache for thread-safe operations and to allow multiple workers
    to update the same progress.
    """

    @staticmethod
    def get_progress_key(exchange_id):
        """Generate a unique cache key for the exchange's sync progress"""
        key = f"exchange_sync_progress_{exchange_id}"
        logger.info(f"Generated progress key: {key}")
        return key

    @staticmethod
    def get_status_key(exchange_id):
        """Generate a unique cache key for the exchange's sync status"""
        key = f"exchange_sync_status_{exchange_id}"
        logger.info(f"Generated status key: {key}")
        return key

    @staticmethod
    def get_error_key(exchange_id):
        """Generate a unique cache key for the exchange's sync error"""
        key = f"exchange_sync_error_{exchange_id}"
        logger.info(f"Generated error key: {key}")
        return key

    @staticmethod
    def initialize_sync(exchange_id):
        """Initialize the sync progress for an exchange"""
        progress_key = SyncProgressService.get_progress_key(exchange_id)
        status_key = SyncProgressService.get_status_key(exchange_id)
        error_key = SyncProgressService.get_error_key(exchange_id)

        logger.info(f"Initializing sync for exchange {exchange_id}")
        logger.info(f"Setting initial progress in Redis - Key: {progress_key}, Value: 0")

        # Set initial progress to 0%
        cache.set(progress_key, 0, timeout=3600)  # 1 hour timeout

        logger.info(f"Setting initial status in Redis - Key: {status_key}, Value: in_progress")
        # Set status to 'in_progress'
        cache.set(status_key, 'in_progress', timeout=3600)
        
        logger.info(f"Clearing error in Redis - Key: {error_key}")
        # Clear any previous error
        cache.delete(error_key)

        # Send WebSocket notification
        try:
            SyncProgressService.send_progress_update(exchange_id)
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {str(e)}")

        return True

    @staticmethod
    def update_progress(exchange_id, progress, message="", details=None):
        """Enhanced progress update with messages and details"""
        progress_key = SyncProgressService.get_progress_key(exchange_id)
        status_key = SyncProgressService.get_status_key(exchange_id)
        message_key = f"exchange_sync_message_{exchange_id}"
        details_key = f"exchange_sync_details_{exchange_id}"

        # Ensure progress is between 0 and 100
        progress = max(0, min(100, progress))

        # Get current progress to avoid unnecessary updates
        current_progress = cache.get(progress_key, 0)
        current_status = cache.get(status_key, 'not_started')

        logger.info(f"Updating progress for exchange {exchange_id}: {progress}% - {message}")

        # Update progress in cache
        cache.set(progress_key, progress, timeout=3600)

        # Store message and details
        if message:
            cache.set(message_key, message, timeout=3600)

        if details:
            cache.set(details_key, details, timeout=3600)

        # Update status based on progress
        if progress >= 100 and current_status != 'completed':
            SyncProgressService.complete_sync(exchange_id)
        elif current_status != 'failed' and progress > 0:
            cache.set(status_key, 'in_progress', timeout=3600)

            # Send WebSocket update
            try:
                SyncProgressService.send_progress_update(exchange_id)
            except Exception as e:
                logger.error(f"Error sending WebSocket notification: {str(e)}")

        return progress

    @staticmethod
    def complete_sync(exchange_id, success=True):
        """Mark a sync operation as completed"""
        status_key = SyncProgressService.get_status_key(exchange_id)
        progress_key = SyncProgressService.get_progress_key(exchange_id)

        # Set progress to 100%
        cache.set(progress_key, 100, timeout=3600)

        # Set status to 'completed' or 'failed'
        status = 'completed' if success else 'failed'
        cache.set(status_key, status, timeout=3600)

        # Send WebSocket notification
        try:
            SyncProgressService.send_progress_update(exchange_id)
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {str(e)}")

        return True

    @staticmethod
    def fail_sync(exchange_id, error_message=None):
        """Mark a sync operation as failed"""
        status_key = SyncProgressService.get_status_key(exchange_id)
        error_key = SyncProgressService.get_error_key(exchange_id)

        # Set status to 'failed'
        cache.set(status_key, 'failed', timeout=3600)

        # Store error message if provided
        if error_message:
            cache.set(error_key, error_message, timeout=3600)

        # Send WebSocket notification
        try:
            SyncProgressService.send_progress_update(exchange_id)
        except Exception as e:
            logger.error(f"Error sending WebSocket notification: {str(e)}")

        return True

    @staticmethod
    def get_progress(exchange_id):
        """Enhanced progress retrieval with messages and details"""
        progress_key = SyncProgressService.get_progress_key(exchange_id)
        status_key = SyncProgressService.get_status_key(exchange_id)
        error_key = SyncProgressService.get_error_key(exchange_id)
        message_key = f"exchange_sync_message_{exchange_id}"
        details_key = f"exchange_sync_details_{exchange_id}"

        # Get all progress data
        progress = cache.get(progress_key, 0)
        status = cache.get(status_key, 'not_started')
        error = cache.get(error_key, None)
        message = cache.get(message_key, "")
        details = cache.get(details_key, {})

        return {
            'progress': progress,
            'status': status,
            'error': error,
            'message': message,
            'details': details,
            'is_complete': status == 'completed',
            'is_failed': status == 'failed',
            'timestamp': int(time.time())
        }

    @staticmethod
    def send_progress_update(exchange_id):
        """Send a progress update via WebSocket"""
        try:
            # Get the progress data
            progress_data = SyncProgressService.get_progress(exchange_id)

            # Get the channel layer
            channel_layer = get_channel_layer()

            # Send to the group for this exchange
            async_to_sync(channel_layer.group_send)(
                f"progress_{exchange_id}",
                {
                    'type': 'progress_update',
                    'exchange_id': exchange_id,
                    'progress': progress_data
                }
            )

            return True
        except Exception as e:
            logger.error(f"Error sending WebSocket progress update: {str(e)}")
            return False