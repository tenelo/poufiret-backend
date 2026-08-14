"""Consumer WebSocket du chat temps réel.
Connexion : ws://host/ws/chat/<conversation_id>/?token=<access>
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class ChatConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']
        self.conv_id = self.scope['url_route']['kwargs']['conversation_id']
        self.group = f'chat_{self.conv_id}'

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)  # non authentifié
            return
        if not await self._participe(self.conv_id, self.user):
            await self.close(code=4003)  # pas membre de la conversation
            return

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group'):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except Exception:
            return
        if data.get('type') == 'marquer_lu':
            ids = await self._marquer_lus(self.conv_id, self.user)
            if ids:
                await self.channel_layer.group_send(self.group, {
                    'type': 'messages_lus',
                    'payload': {'type': 'messages_lus', 'lecteur': self.user.id,
                                'message_ids': ids},
                })
            return
        contenu = (data.get('contenu') or '').strip()
        if not contenu:
            return
        msg = await self._enregistrer(self.conv_id, self.user, contenu)
        # Diffuse à tous les participants connectés
        await self.channel_layer.group_send(self.group, {
            'type': 'chat_message',
            'message': {
                'id': msg['id'],
                'conversation': int(self.conv_id),
                'expediteur': msg['expediteur'],
                'expediteur_nom': msg['expediteur_nom'],
                'contenu': msg['contenu'],
                'created_at': msg['created_at'],
            },
        })

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event['message'], ensure_ascii=False))
    async def messages_lus(self, event):
        await self.send(text_data=json.dumps(event['payload'], ensure_ascii=False))

    # ── Accès base (sync -> async) ────────────────────────────────────
    @database_sync_to_async
    def _participe(self, conv_id, user):
        from .models import Conversation
        c = Conversation.objects.filter(pk=conv_id).select_related('partenaire').first()
        if not c:
            return False
        if c.client_id == user.id:
            return True
        return hasattr(user, 'profil_partenaire') and c.partenaire_id == user.profil_partenaire.id

    @database_sync_to_async
    def _marquer_lus(self, conv_id, user):
        from django.utils import timezone
        from .models import Message
        qs = Message.objects.filter(
            conversation_id=conv_id,
        ).exclude(expediteur=user).exclude(statut=Message.Statut.LU)
        ids = list(qs.values_list('id', flat=True))
        if ids:
            qs.update(statut=Message.Statut.LU, lu_le=timezone.now())
        return ids
    @database_sync_to_async
    def _enregistrer(self, conv_id, user, contenu):
        from .models import Conversation, Message
        c = Conversation.objects.get(pk=conv_id)
        m = Message.objects.create(conversation=c, expediteur=user, contenu=contenu)
        Conversation.objects.filter(pk=conv_id).update(derniere_activite=m.created_at)
        # Notifie le destinataire (l'autre participant) par push FCM.
        try:
            from apps.notifications.fcm import notifier_utilisateur
            nom = user.get_full_name() or user.username or user.telephone
            if c.client_id == user.id:
                destinataire = c.partenaire.user
            else:
                destinataire = c.client
            notifier_utilisateur(
                destinataire,
                titre=f'Nouveau message de {nom}',
                corps=contenu[:120],
                data={'type': 'message', 'conversation_id': str(conv_id),
                      'expediteur_nom': nom},
            )
        except Exception:
            pass  # une notification ratee ne doit jamais bloquer le chat
        return {
            'id': m.id, 'expediteur': user.id,
            'expediteur_nom': user.get_full_name() or user.username or user.telephone,
            'contenu': m.contenu, 'created_at': m.created_at.isoformat(),
        }
