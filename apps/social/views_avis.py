"""Avis clients : création / modification (client), liste publique d'un
partenaire, réponse du partenaire, modération admin (gerer_avis).
Règles : apps.social.avis ; refus en ErreurMetier (message clair)."""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ErreurMetier
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from . import avis as regles
from .models import Avis


def _nom_public(user):
    """Prénom + initiale du nom (jamais le téléphone) pour l'affichage public."""
    prenom = (user.first_name or '').strip()
    initiale = (user.last_name or '').strip()[:1]
    return f'{prenom} {initiale}.'.strip() if prenom and initiale else (prenom or 'Client')


class AvisSerializer(serializers.ModelSerializer):
    """Avis complet (auteur, admin)."""
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True, default=None)
    auteur_nom = serializers.SerializerMethodField()
    modifiable_jusqu_au = serializers.SerializerMethodField()

    class Meta:
        model = Avis
        fields = ['id', 'objet_type', 'objet_id', 'partenaire', 'partenaire_nom', 'livreur',
                  'auteur', 'auteur_nom', 'note', 'commentaire', 'est_visible',
                  'reponse_partenaire', 'repondu_le', 'cree_le', 'modifie_le', 'modifiable_jusqu_au']
        read_only_fields = fields

    def get_auteur_nom(self, obj):
        return _nom_public(obj.auteur)

    def get_modifiable_jusqu_au(self, obj):
        return regles.modifiable_jusqu_au(obj)


class AvisPublicSerializer(serializers.ModelSerializer):
    """Avis visible publiquement (sans données personnelles)."""
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = Avis
        fields = ['id', 'objet_type', 'auteur_nom', 'note', 'commentaire',
                  'reponse_partenaire', 'repondu_le', 'cree_le']
        read_only_fields = fields

    def get_auteur_nom(self, obj):
        return _nom_public(obj.auteur)


class _SaisieAvisSerializer(serializers.Serializer):
    note = serializers.IntegerField(min_value=1, max_value=5)
    commentaire = serializers.CharField(required=False, allow_blank=True, max_length=1000, default='')


def _valider(serializer_class, donnees, partial=False):
    ser = serializer_class(data=donnees, partial=partial)
    if not ser.is_valid():
        raise ErreurMetier('Avis invalide : vérifiez la note (1 à 5) et le commentaire (1000 caractères max).',
                           ser.errors)
    return ser.validated_data


class AvisCreerView(APIView):
    """POST /api/v1/avis/ {objet_type, objet_id, note, commentaire?} — par le
    client de l'objet, une fois l'objet livré / terminé, un seul avis par objet."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        objet_type = request.data.get('objet_type')
        objet_id = str(request.data.get('objet_id') or '').strip()
        objet = regles.charger_objet(objet_type, objet_id)
        refus = regles.raison_refus(request.user, objet_type, objet)
        if refus:
            raise ErreurMetier(refus[0], status_code=refus[1])
        if Avis.objects.filter(auteur=request.user, objet_type=objet_type, objet_id=str(objet.pk)).exists():
            raise ErreurMetier('Vous avez déjà donné votre avis : modifiez-le plutôt.', status_code=409)
        donnees = _valider(_SaisieAvisSerializer, request.data)
        partenaire, livreur = regles.cibles(objet_type, objet)
        try:
            with transaction.atomic():
                avis = Avis.objects.create(
                    auteur=request.user, objet_type=objet_type, objet_id=str(objet.pk),
                    partenaire=partenaire, livreur=livreur,
                    note=donnees['note'], commentaire=donnees.get('commentaire', ''))
        except IntegrityError:  # deux envois simultanés
            raise ErreurMetier('Vous avez déjà donné votre avis : modifiez-le plutôt.', status_code=409)
        regles.recalculer_note_partenaire(avis.partenaire_id)
        return Response(AvisSerializer(avis).data, status=status.HTTP_201_CREATED)


class AvisModifierView(APIView):
    """PATCH /api/v1/avis/<id>/ {note?, commentaire?} — par son auteur, 7 jours."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk=None):
        avis = Avis.objects.filter(pk=pk).select_related('auteur', 'partenaire').first()
        if avis is None:
            raise ErreurMetier('Avis introuvable.', status_code=404)
        regles.verifier_modifiable(avis, request.user)
        donnees = _valider(_SaisieAvisSerializer, request.data, partial=True)
        for champ in ('note', 'commentaire'):
            if champ in donnees:
                setattr(avis, champ, donnees[champ])
        avis.save()
        regles.recalculer_note_partenaire(avis.partenaire_id)
        return Response(AvisSerializer(avis).data)


class MesAvisView(generics.ListAPIView):
    """GET /api/v1/avis/mes-avis/ — avis du client connecté (masqués compris)."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AvisSerializer

    def get_queryset(self):
        return (Avis.objects.filter(auteur=self.request.user)
                .select_related('auteur', 'partenaire').order_by('-cree_le'))


class AvisPartenaireView(generics.ListAPIView):
    """GET /api/v1/partenaires/<id>/avis/ — avis visibles d'un partenaire (paginé)
    + résumé {note_moyenne, nb_avis} à la racine."""
    permission_classes = [permissions.AllowAny]
    serializer_class = AvisPublicSerializer

    def get_queryset(self):
        self.partenaire = get_object_or_404(ProfilPartenaire, pk=self.kwargs['pk'])
        return (Avis.objects.filter(partenaire=self.partenaire, est_visible=True)
                .select_related('auteur').order_by('-cree_le'))

    def list(self, request, *args, **kwargs):
        reponse = super().list(request, *args, **kwargs)
        if isinstance(reponse.data, dict):
            reponse.data['note_moyenne'] = self.partenaire.note_moyenne
            reponse.data['nb_avis'] = self.partenaire.nb_avis
        return reponse


class RepondreAvisView(APIView):
    """POST /api/v1/avis/<id>/repondre/ {reponse} — le partenaire noté, une fois."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        avis = Avis.objects.filter(pk=pk).select_related('auteur', 'partenaire').first()
        if avis is None:
            raise ErreurMetier('Avis introuvable.', status_code=404)
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None or avis.partenaire_id != profil.id:
            raise ErreurMetier('Vous ne pouvez répondre qu\'aux avis sur votre établissement.', status_code=403)
        if avis.reponse_partenaire:
            raise ErreurMetier('Vous avez déjà répondu à cet avis.', status_code=409)
        reponse = (request.data.get('reponse') or '').strip()
        if not reponse or len(reponse) > 1000:
            raise ErreurMetier('Réponse requise (1000 caractères max).')
        avis.reponse_partenaire = reponse
        avis.repondu_le = timezone.now()
        avis.save(update_fields=['reponse_partenaire', 'repondu_le', 'modifie_le'])
        return Response(AvisSerializer(avis).data)


class AdminAvisListView(generics.ListAPIView):
    """GET /api/v1/avis/admin/?partenaire=&note=&visible=1|0&objet_type=&q=&du=&au=
    — tous les avis (paginé), réservé à gerer_avis (super-admin toujours)."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_avis')]
    serializer_class = AvisSerializer

    def get_queryset(self):
        from datetime import datetime
        p = self.request.query_params
        qs = Avis.objects.select_related('auteur', 'partenaire').order_by('-cree_le')
        if p.get('partenaire'):
            qs = qs.filter(partenaire_id=p['partenaire']) if p['partenaire'].isdigit() else qs.none()
        if p.get('note'):
            qs = qs.filter(note=p['note']) if p['note'] in {'1', '2', '3', '4', '5'} else qs.none()
        if p.get('visible') in ('1', '0'):
            qs = qs.filter(est_visible=p['visible'] == '1')
        if p.get('objet_type'):
            qs = qs.filter(objet_type=p['objet_type'])
        q = (p.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(commentaire__icontains=q) | Q(partenaire__nom_commerce__icontains=q)
                           | Q(auteur__telephone__icontains=q) | Q(auteur__first_name__icontains=q)
                           | Q(auteur__last_name__icontains=q))
        for cle, lookup in (('du', 'cree_le__date__gte'), ('au', 'cree_le__date__lte')):
            try:
                qs = qs.filter(**{lookup: datetime.strptime(p[cle][:10], '%Y-%m-%d').date()}) if p.get(cle) else qs
            except ValueError:
                pass
        return qs


class AdminAvisDetailView(APIView):
    """PATCH /api/v1/avis/admin/<id>/ {est_visible, motif?} — masquer / réafficher,
    tracé dans JournalModeration (avis_masque / avis_affiche) ; note du
    partenaire recalculée."""
    permission_classes = [permissions.IsAuthenticated, ADroitDe('gerer_avis')]

    def patch(self, request, pk=None):
        from apps.administration.models import JournalModeration
        avis = Avis.objects.filter(pk=pk).select_related('auteur', 'partenaire').first()
        if avis is None:
            raise ErreurMetier('Avis introuvable.', status_code=404)
        visible = request.data.get('est_visible')
        if not isinstance(visible, bool):
            raise ErreurMetier('est_visible (booléen) requis.')
        if visible != avis.est_visible:
            avis.est_visible = visible
            avis.save(update_fields=['est_visible', 'modifie_le'])
            regles.recalculer_note_partenaire(avis.partenaire_id)
            motif = (request.data.get('motif') or '').strip()
            JournalModeration.enregistrer(
                request.user, avis.auteur,
                JournalModeration.Action.AVIS_AFFICHE if visible else JournalModeration.Action.AVIS_MASQUE,
                (f'Avis #{avis.id} ({avis.note}/5) sur « {getattr(avis.partenaire, "nom_commerce", "—")} »'
                 + (f' : {motif}' if motif else ''))[:255])
        return Response(AvisSerializer(avis).data)
