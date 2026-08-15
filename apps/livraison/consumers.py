"""Consumer WebSocket du positionnement livreur en temps reel.

Connexion : ws://host/ws/course/<course_id>/position/?token=<access>

Trois acteurs d'une course peuvent se connecter : le livreur assigne, le
demandeur, et le destinataire (contact_user). Seul le livreur peut EMETTRE
sa position ; les autres la RECOIVENT. Se greffe sur l'infra Channels du chat.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class PositionCourseConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']
        self.course_id = self.scope['url_route']['kwargs']['course_id']
        self.group = f'course_pos_{self.course_id}'

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return
        role = await self._role(self.course_id, self.user)
        if role is None:
            await self.close(code=4003)  # pas un acteur de la course
            return
        self.est_livreur = (role == 'livreur')

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group'):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Seul le livreur assigne peut emettre sa position.
        if not getattr(self, 'est_livreur', False):
            return
        try:
            data = json.loads(text_data)
            lat = float(data['latitude'])
            lng = float(data['longitude'])
        except Exception:
            return
        maj = await self._enregistrer_position(self.user, lat, lng)
        if maj is None:
            return
        await self.channel_layer.group_send(self.group, {
            'type': 'position_livreur',
            'payload': {'type': 'position', 'latitude': lat, 'longitude': lng,
                        'maj_le': maj},
        })

    async def position_livreur(self, event):
        await self.send(text_data=json.dumps(event['payload'], ensure_ascii=False))

    # ── Acces base (sync -> async) ────────────────────────────────────
    @database_sync_to_async
    def _role(self, course_id, user):
        """Retourne 'livreur' / 'demandeur' / 'destinataire' selon le lien de
        l'utilisateur a la course, ou None s'il n'y est pas partie."""
        from apps.livraison.models import Course
        c = Course.objects.filter(pk=course_id).select_related('livreur').first()
        if not c:
            return None
        if c.livreur and c.livreur.user_id == user.id:
            return 'livreur'
        if c.demandeur_id == user.id:
            return 'demandeur'
        if c.contact_user_id == user.id:
            return 'destinataire'
        return None

    @database_sync_to_async
    def _enregistrer_position(self, user, lat, lng):
        from django.contrib.gis.geos import Point
        from django.utils import timezone
        from apps.livreurs.models import Livreur
        liv = Livreur.objects.filter(user=user).first()
        if not liv:
            return None
        liv.position = Point(lng, lat, srid=4326)
        liv.position_maj_le = timezone.now()
        liv.save(update_fields=['position', 'position_maj_le'])
        return liv.position_maj_le.isoformat()
