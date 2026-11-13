"""Consumer WebSocket des notifications admin (compteurs en temps réel).
Connexion : wss://host/ws/notifications/admin/?token=<access>
Refus : 4001 (non authentifié ou compte inactif), 4003 (pas admin).
"""
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .temps_reel import compteurs_admin, groupe_admin


class NotificationsAdminConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated or not user.is_active:
            await self.close(code=4001)
            return
        # Même règle que EstAdminOuSuperAdmin (REST).
        if not (user.is_staff or user.is_superuser):
            await self.close(code=4003)
            return
        self.group = groupe_admin(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        compteurs = await database_sync_to_async(compteurs_admin)(user)
        await self._envoyer({'type': 'compteurs', **compteurs, 'nouvelle': False})

    async def disconnect(self, code):
        if hasattr(self, 'group'):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Canal descendant uniquement : les messages du client sont ignorés."""
        return

    async def compteurs_admin(self, event):
        await self._envoyer(event['payload'])

    async def _envoyer(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False))
