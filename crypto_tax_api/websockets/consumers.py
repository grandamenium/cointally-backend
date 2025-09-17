# websockets/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from crypto_tax_api.models import ExchangeCredential
from crypto_tax_api.services.sync_progress_service import SyncProgressService


class ProgressConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time progress updates.
    Allows clients to subscribe to progress updates for specific exchanges
    without polling the API.
    """

    async def connect(self):
        # Accept connection
        await self.accept()

        # Store subscriptions
        self.subscriptions = set()

    async def disconnect(self, close_code):
        # Clean up subscriptions
        for exchange_id in self.subscriptions:
            await self.channel_layer.group_discard(
                f"progress_{exchange_id}",
                self.channel_name
            )

        self.subscriptions.clear()

    async def receive(self, text_data):
        """
        Receive message from WebSocket.
        Expected format: {"action": "subscribe|unsubscribe", "exchange_id": "123"}
        """
        try:
            data = json.loads(text_data)
            action = data.get('action')
            exchange_id = data.get('exchange_id')

            if not action or not exchange_id:
                await self.send(json.dumps({
                    'error': 'Invalid message format. Expected {"action": "...", "exchange_id": "..."}'
                }))
                return

            # Validate that the user has permission to access this exchange
            if not await self.has_exchange_permission(exchange_id):
                await self.send(json.dumps({
                    'error': 'Permission denied for this exchange'
                }))
                return

            # Handle subscribe action
            if action == 'subscribe':
                # Add to channel group
                await self.channel_layer.group_add(
                    f"progress_{exchange_id}",
                    self.channel_name
                )

                # Add to subscriptions
                self.subscriptions.add(exchange_id)

                # Send current progress immediately
                progress_data = await database_sync_to_async(SyncProgressService.get_progress)(exchange_id)
                await self.send(json.dumps({
                    'type': 'progress_update',
                    'exchange_id': exchange_id,
                    'progress': progress_data
                }))

                # Confirm subscription
                await self.send(json.dumps({
                    'type': 'subscription_status',
                    'exchange_id': exchange_id,
                    'status': 'subscribed'
                }))

            # Handle unsubscribe action
            elif action == 'unsubscribe':
                # Remove from channel group
                await self.channel_layer.group_discard(
                    f"progress_{exchange_id}",
                    self.channel_name
                )

                # Remove from subscriptions
                if exchange_id in self.subscriptions:
                    self.subscriptions.remove(exchange_id)

                # Confirm unsubscription
                await self.send(json.dumps({
                    'type': 'subscription_status',
                    'exchange_id': exchange_id,
                    'status': 'unsubscribed'
                }))

            # Handle unknown action
            else:
                await self.send(json.dumps({
                    'error': f'Unknown action: {action}'
                }))

        except json.JSONDecodeError:
            await self.send(json.dumps({
                'error': 'Invalid JSON'
            }))

        except Exception as e:
            await self.send(json.dumps({
                'error': f'Error: {str(e)}'
            }))

    async def progress_update(self, event):
        """
        Receive progress update from channel layer
        and forward it to the WebSocket.
        """
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'progress_update',
            'exchange_id': event['exchange_id'],
            'progress': event['progress']  # This contains the full progress data object
        }))

    @database_sync_to_async
    def has_exchange_permission(self, exchange_id):
        """
        Check if the current user has permission to access this exchange
        """
        # Anonymous users don't have permissions
        if not self.scope['user'] or not self.scope['user'].is_authenticated:
            return False

        # Check if the exchange belongs to the user
        try:
            ExchangeCredential.objects.get(
                id=exchange_id,
                user=self.scope['user']
            )
            return True
        except ExchangeCredential.DoesNotExist:
            return False
