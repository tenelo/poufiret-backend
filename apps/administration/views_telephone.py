"""Changement du numéro de connexion d'un partenaire, par un admin autorisé
(capacité modifier_identifiant_partenaire, privilégiée). Le partenaire ne
peut pas encore le changer lui-même ; le PIN ne change pas.

Réutilise _journaliser et _revoquer_sessions de apps.administration.moderation.
"""
import functools
import re

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.core.permissions import ADroitDe
from apps.moderation.models import Notification
from apps.notifications.fcm import notifier_utilisateur
from apps.users.models import NumeroVerifie, ProfilPartenaire, User

from .moderation import _journaliser, _revoquer_sessions
from .models import JournalModeration

_PERMISSION = [IsAuthenticated, ADroitDe('modifier_identifiant_partenaire')]
_FORMAT_HISTORIQUE = re.compile(r'^(?P<ancien>\S+) → (?P<nouveau>\S+) — (?P<motif>.*)$', re.DOTALL)


def normaliser_telephone_ci(brut):
    """0XXXXXXXXX ou +225XXXXXXXXXX → +225XXXXXXXXXX ; None sinon."""
    s = re.sub(r'[\s.\-()]', '', str(brut or ''))
    if re.fullmatch(r'0\d{9}', s):
        return '+225' + s
    if re.fullmatch(r'\+225\d{10}', s):
        return s
    return None


def _meme_numero(a, b):
    na, nb = normaliser_telephone_ci(a), normaliser_telephone_ci(b)
    return na is not None and na == nb


def _blacklister_refresh_tokens(user):
    for jeton in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=jeton)


def _notifier_changement_telephone(cible, nouveau, message):
    Notification.objects.create(
        user=cible, type=Notification.Type.COMPTE_TELEPHONE_MODIFIE,
        titre='Numéro de connexion modifié', contenu=message,
        data={'nouveau_telephone': nouveau})
    notifier_utilisateur(cible, 'Numéro de connexion modifié', message,
                         data={'type': 'compte', 'sous_type': 'telephone_modifie'})


def _profil_partenaire(pk):
    return ProfilPartenaire.objects.select_related('user').filter(pk=pk).first()


class ChangerTelephonePartenaireView(APIView):
    """POST /administration/partenaires/<id>/changer-telephone/
    pk = id du ProfilPartenaire (même identifiant que la fiche admin)."""
    permission_classes = _PERMISSION

    def post(self, request, pk):
        profil = _profil_partenaire(pk)
        if profil is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'}, status=404)
        cible = profil.user
        if cible.is_staff or cible.is_superuser or cible.role != User.Role.PARTENAIRE:
            return Response({'erreur': True, 'message': "Ce compte n'est pas un compte partenaire."},
                            status=400)

        erreurs = {}
        nouveau = normaliser_telephone_ci(request.data.get('nouveau_telephone'))
        if nouveau is None:
            erreurs['nouveau_telephone'] = [
                'Numéro invalide : format attendu 0XXXXXXXXX ou +225XXXXXXXXXX.']
        motif = str(request.data.get('motif') or '').strip()
        if not motif:
            erreurs['motif'] = ['Le motif est obligatoire.']
        if erreurs:
            return Response({'erreur': True, 'details': erreurs}, status=400)

        ancien = cible.telephone
        if nouveau == ancien:
            return Response({'erreur': True, 'details': {'nouveau_telephone': [
                'Ce numéro est déjà le numéro de connexion de ce partenaire.']}}, status=400)
        if User.objects.filter(telephone=nouveau).exclude(pk=cible.pk).exists():
            return Response({'erreur': True,
                             'message': 'Ce numéro est déjà utilisé par un autre compte.'}, status=409)

        aussi_pro = request.data.get('aussi_telephone_pro') in (True, 'true', 'True', '1', 1)
        message_push = (f"Votre numéro de connexion a été changé par l'administration. "
                        f"Connectez-vous désormais avec le {nouveau} et votre PIN habituel.")

        with transaction.atomic():
            cible.telephone = nouveau
            cible.save(update_fields=['telephone'])
            NumeroVerifie.objects.update_or_create(
                telephone=nouveau, defaults={'source': NumeroVerifie.Source.ADMIN})
            if aussi_pro:
                profil.telephone_pro = nouveau
                if _meme_numero(profil.whatsapp, ancien):
                    profil.whatsapp = nouveau
                profil.save(update_fields=['telephone_pro', 'whatsapp'])

            transaction.on_commit(functools.partial(_notifier_changement_telephone, cible, nouveau, message_push))

            _blacklister_refresh_tokens(cible)
            _revoquer_sessions(cible, request.user)
            _journaliser(request.user, cible, JournalModeration.Action.PARTENAIRE_TELEPHONE_MODIF,
                         f'{ancien} → {nouveau} — {motif}'[:255])

        return Response({
            'id': profil.id,
            'telephone': nouveau,
            'telephone_pro': profil.telephone_pro,
            'whatsapp': profil.whatsapp,
            'message': "Numéro de connexion modifié. Le partenaire a été déconnecté de tous ses appareils.",
        })


class HistoriqueTelephonePartenaireView(APIView):
    """GET /administration/partenaires/<id>/historique-telephone/ — depuis le journal."""
    permission_classes = _PERMISSION

    def get(self, request, pk):
        profil = _profil_partenaire(pk)
        if profil is None:
            return Response({'erreur': True, 'message': 'Partenaire introuvable.'}, status=404)
        entrees = (JournalModeration.objects
                   .filter(cible=profil.user, action=JournalModeration.Action.PARTENAIRE_TELEPHONE_MODIF)
                   .select_related('acteur').order_by('-cree_le'))
        resultats = []
        for e in entrees:
            m = _FORMAT_HISTORIQUE.match(e.motif or '')
            acteur = e.acteur
            resultats.append({
                'ancien': m.group('ancien') if m else '',
                'nouveau': m.group('nouveau') if m else e.cible_identifiant,
                'motif': m.group('motif') if m else e.motif,
                'auteur_nom': (acteur.get_full_name() or acteur.username or acteur.telephone) if acteur else '',
                'cree_le': e.cree_le,
            })
        return Response({'resultats': resultats})
