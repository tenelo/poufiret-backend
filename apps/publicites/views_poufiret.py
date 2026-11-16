"""Pubs Poufiret (pubs maison du carrousel) et parcours « Découvrir Poufiret ».

Admin (capacité gerer_pubs_poufiret, super-admin toujours) — /api/v1/publicites/admin/poufiret/ :
    pubs/                 GET liste paginée (?est_active=true|false, ?en_cours=true,
                          ?export=csv) ; POST création (multipart, image obligatoire)
    pubs/<id>/            GET / PATCH (multipart possible) / DELETE
    pubs/ordre/           POST {"ids": [...]} : ordre = position dans la liste
    pubs/<id>/stats/      GET stats d'une pub
    stats/                GET ?du=&au= (AAAA-MM-JJ, défaut 30 derniers jours)
    ecrans/               GET tous les écrans ; POST création
    ecrans/<id>/          GET / PATCH / DELETE
    ecrans/ordre/         POST {"ids": [...]}
    parcours/publier/     POST : 3 à 8 écrans actifs, version_parcours + 1
    reglages/             GET / PATCH

App (public, sans authentification) :
    carrousel/                    clé `elements` (voir services_poufiret.elements_carrousel)
    poufiret/<id>/impression/     POST {cliquee, type_affichage, session_id, minute_session}
    decouvrir/                    GET {actif, version, ecrans}
"""
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exports import reponse_csv
from apps.core.pagination import StandardPagination
from apps.core.permissions import ADroitDe

from . import services_poufiret as sp
from .models import (EcranDecouverte, ImpressionPubPoufiret, ParametresPoufiret,
                     PubPoufiret, TypeAffichage)
from .serializers_poufiret import (EcranDecouverteAdminSerializer, ParametresPoufiretSerializer,
                                   PubPoufiretAdminSerializer)

_PERMISSION = [permissions.IsAuthenticated, ADroitDe('gerer_pubs_poufiret')]


def _erreur(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'erreur': True, 'message': message}, status=code)


def _journaliser(acteur, action, motif):
    """Best-effort, comme les autres actions admin des pubs."""
    try:
        from apps.administration.moderation import _journaliser as journal
        journal(acteur, None, action, motif[:255])
    except Exception:
        pass


def _booleen(valeur):
    return None if valeur in (None, '') else str(valeur).lower() in ('1', 'true', 'oui', 'yes')


def _reordonner(modele, ids):
    """ordre = position dans `ids` (tous doivent exister). Retourne une
    erreur (str) ou None."""
    if not isinstance(ids, list) or not ids:
        return 'Liste « ids » attendue (identifiants dans le nouvel ordre).'
    ids = [str(i) for i in ids]
    if len(set(ids)) != len(ids):
        return 'Identifiant en double dans « ids ».'
    try:
        objets = {str(o.pk): o for o in modele.objects.filter(pk__in=ids)}
    except Exception:
        return 'Identifiant invalide dans « ids ».'
    inconnus = [i for i in ids if i not in objets]
    if inconnus:
        return f'Identifiant inconnu : {", ".join(inconnus)}.'
    for position, i in enumerate(ids):
        objets[i].ordre = position
    modele.objects.bulk_update(objets.values(), ['ordre'])
    return None


# ═══════════════════════════════════════════════════════════════════════
# Admin : pubs Poufiret
# ═══════════════════════════════════════════════════════════════════════

class PubsPoufiretAdminView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        p = request.query_params
        qs = PubPoufiret.objects.select_related('categorie').order_by('ordre', 'cree_le')
        est_active = _booleen(p.get('est_active'))
        if est_active is not None:
            qs = qs.filter(est_active=est_active)
        if _booleen(p.get('en_cours')):
            maintenant = timezone.now()
            qs = qs.filter(est_active=True).filter(
                Q(date_debut__isnull=True) | Q(date_debut__lte=maintenant)).filter(
                Q(date_fin__isnull=True) | Q(date_fin__gt=maintenant))
        accessibles = sp.categories_accessibles()
        if p.get('export') == 'csv':
            return reponse_csv('pubs_poufiret', [
                'id', 'titre', 'categorie', 'categorie_disponible', 'portee', 'region', 'departement',
                'date_debut', 'date_fin', 'active', 'ordre', 'affichages', 'clics', 'taux_clic',
                'personnes_touchees'],
                ([x.id, x.titre, x.categorie.nom if x.categorie else '',
                  'oui' if x.categorie_id in accessibles else 'non', x.portee,
                  x.region.nom if x.region else '', x.departement.nom if x.departement else '',
                  timezone.localtime(x.date_debut).strftime('%d/%m/%Y %H:%M') if x.date_debut else '',
                  timezone.localtime(x.date_fin).strftime('%d/%m/%Y %H:%M') if x.date_fin else '',
                  'oui' if x.est_active else 'non', x.ordre, x.nb_impressions, x.nb_clics,
                  sp.taux_clic(x.nb_clics, x.nb_impressions), x.nb_personnes_touchees]
                 for x in qs.select_related('region', 'departement')))
        paginateur = StandardPagination()
        page = paginateur.paginate_queryset(qs, request, view=self)
        contexte = {'request': request, 'accessibles': accessibles,
                    'par_type': sp.impressions_par_type([x.pk for x in page])}
        return paginateur.get_paginated_response(
            PubPoufiretAdminSerializer(page, many=True, context=contexte).data)

    def post(self, request):
        if not request.data.get('image_couverture'):
            return _erreur('Image obligatoire.')
        s = PubPoufiretAdminSerializer(data=request.data, context={'request': request})
        s.is_valid(raise_exception=True)
        pub = s.save(cree_par=request.user)
        _journaliser(request.user, 'pub_poufiret_creer', f'Pub Poufiret « {pub.titre} » ({pub.id}) créée.')
        return Response(PubPoufiretAdminSerializer(pub, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class PubPoufiretAdminDetailView(APIView):
    permission_classes = _PERMISSION

    def get(self, request, pk):
        pub = get_object_or_404(PubPoufiret, pk=pk)
        return Response(PubPoufiretAdminSerializer(pub, context={'request': request}).data)

    def patch(self, request, pk):
        pub = get_object_or_404(PubPoufiret, pk=pk)
        s = PubPoufiretAdminSerializer(pub, data=request.data, partial=True, context={'request': request})
        s.is_valid(raise_exception=True)
        pub = s.save()
        _journaliser(request.user, 'pub_poufiret_modif',
                     f'Pub Poufiret « {pub.titre} » ({pub.id}) modifiée : {", ".join(sorted(request.data))}.')
        return Response(PubPoufiretAdminSerializer(pub, context={'request': request}).data)

    def delete(self, request, pk):
        pub = get_object_or_404(PubPoufiret, pk=pk)
        titre, ident = pub.titre, pub.id
        pub.delete()
        _journaliser(request.user, 'pub_poufiret_suppr', f'Pub Poufiret « {titre} » ({ident}) supprimée.')
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrdrePubsPoufiretView(APIView):
    permission_classes = _PERMISSION

    def post(self, request):
        erreur = _reordonner(PubPoufiret, request.data.get('ids'))
        if erreur:
            return _erreur(erreur)
        return Response({'ids': [str(i) for i in PubPoufiret.objects.order_by(
            'ordre', 'cree_le').values_list('id', flat=True)]})


class StatsPubPoufiretView(APIView):
    permission_classes = _PERMISSION

    def get(self, request, pk):
        pub = get_object_or_404(PubPoufiret, pk=pk)
        return Response({'id': str(pub.id), 'titre': pub.titre, **sp.stats_pub(pub)})


def _date(valeur):
    try:
        return datetime.strptime(valeur.strip(), '%Y-%m-%d').date()
    except (AttributeError, ValueError):
        return None


class StatsPoufiretAdminView(APIView):
    """GET stats/?du=&au= : affichages, clics, taux de clic, personnes
    touchées (utilisateurs distincts) et répartition par emplacement sur la
    période, au global et par pub. Agrégé en base."""
    permission_classes = _PERMISSION

    def get(self, request):
        p = request.query_params
        if (p.get('du') and not _date(p['du'])) or (p.get('au') and not _date(p['au'])):
            return _erreur('Date invalide (format attendu AAAA-MM-JJ).')
        au = _date(p.get('au')) or timezone.localdate()
        du = _date(p.get('du')) or (au - timedelta(days=30))
        if du > au:
            return _erreur('La date de début est postérieure à la date de fin.')
        imps = ImpressionPubPoufiret.objects.filter(cree_le__date__gte=du, cree_le__date__lte=au).order_by()
        clic = Q(cliquee=True)
        g = imps.aggregate(impressions=Count('id'), clics=Count('id', filter=clic),
                           personnes=Count('utilisateur', distinct=True))
        par_type = dict(imps.values_list('type_affichage').annotate(n=Count('id')))
        par_pub = imps.values('pub_id', titre=F('pub__titre')).annotate(
            impressions=Count('id'), clics=Count('id', filter=clic),
            personnes=Count('utilisateur', distinct=True)).order_by('-impressions')
        return Response({
            'du': du, 'au': au,
            'nb_impressions': g['impressions'], 'nb_clics': g['clics'],
            'taux_clic': sp.taux_clic(g['clics'], g['impressions']),
            'nb_personnes_touchees': g['personnes'],
            'impressions_par_type': par_type,
            'par_pub': [{'id': str(x['pub_id']), 'titre': x['titre'], 'nb_impressions': x['impressions'],
                         'nb_clics': x['clics'], 'taux_clic': sp.taux_clic(x['clics'], x['impressions']),
                         'nb_personnes_touchees': x['personnes']} for x in par_pub],
        })


# ═══════════════════════════════════════════════════════════════════════
# Admin : parcours « Découvrir Poufiret » et réglages
# ═══════════════════════════════════════════════════════════════════════

class EcransDecouverteAdminView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        ecrans = EcranDecouverte.objects.select_related('bouton_categorie').order_by('ordre', 'cree_le')
        return Response({'ecrans': EcranDecouverteAdminSerializer(
            ecrans, many=True, context={'request': request}).data})

    def post(self, request):
        if not request.data.get('image'):
            return _erreur('Image obligatoire.')
        s = EcranDecouverteAdminSerializer(data=request.data, context={'request': request})
        s.is_valid(raise_exception=True)
        ecran = s.save()
        return Response(EcranDecouverteAdminSerializer(ecran, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class EcranDecouverteAdminDetailView(APIView):
    permission_classes = _PERMISSION

    def get(self, request, pk):
        return Response(EcranDecouverteAdminSerializer(
            get_object_or_404(EcranDecouverte, pk=pk), context={'request': request}).data)

    def patch(self, request, pk):
        ecran = get_object_or_404(EcranDecouverte, pk=pk)
        s = EcranDecouverteAdminSerializer(ecran, data=request.data, partial=True, context={'request': request})
        s.is_valid(raise_exception=True)
        return Response(EcranDecouverteAdminSerializer(s.save(), context={'request': request}).data)

    def delete(self, request, pk):
        get_object_or_404(EcranDecouverte, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrdreEcransDecouverteView(APIView):
    permission_classes = _PERMISSION

    def post(self, request):
        erreur = _reordonner(EcranDecouverte, request.data.get('ids'))
        if erreur:
            return _erreur(erreur)
        return Response({'ids': [str(i) for i in EcranDecouverte.objects.order_by(
            'ordre', 'cree_le').values_list('id', flat=True)]})


class PublierParcoursView(APIView):
    """POST : vérifie 3 à 8 écrans actifs puis incrémente version_parcours
    (l'app remontrera le parcours une fois)."""
    permission_classes = _PERMISSION

    def post(self, request):
        raison = sp.raison_refus_parcours()
        if raison:
            return _erreur(raison)
        with transaction.atomic():
            params = ParametresPoufiret.obtenir()
            params = ParametresPoufiret.objects.select_for_update().get(pk=params.pk)
            params.version_parcours += 1
            params.save(update_fields=['version_parcours', 'modifie_le'])
        nb = sp.ecrans_actifs().count()
        _journaliser(request.user, 'poufiret_parcours',
                     f'Parcours « Découvrir Poufiret » publié : version {params.version_parcours}, {nb} écrans.')
        return Response({'version_parcours': params.version_parcours, 'nb_ecrans': nb,
                         'parcours_actif': params.parcours_actif})


class ReglagesPoufiretView(APIView):
    permission_classes = _PERMISSION

    def get(self, request):
        return Response(ParametresPoufiretSerializer(ParametresPoufiret.obtenir()).data)

    def patch(self, request):
        params = ParametresPoufiret.obtenir()
        s = ParametresPoufiretSerializer(params, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        champs = ['pubs_maison_actives', 'frequence_pub_maison', 'duree_affichage_secondes', 'parcours_actif']
        avant = {c: getattr(params, c) for c in champs}
        params = s.save()
        modifies = [f'{c} : {avant[c]} -> {getattr(params, c)}' for c in champs if avant[c] != getattr(params, c)]
        if modifies:
            _journaliser(request.user, 'poufiret_reglages', 'Réglages Poufiret : ' + ' ; '.join(modifies))
        return Response(ParametresPoufiretSerializer(params).data)


# ═══════════════════════════════════════════════════════════════════════
# App (public)
# ═══════════════════════════════════════════════════════════════════════

class ImpressionPubPoufiretView(APIView):
    """POST poufiret/<id>/impression/ — affichage ou clic d'une pub
    Poufiret (même corps que /publicites/<id>/impression/)."""
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk):
        pub = PubPoufiret.objects.filter(pk=pk).first()
        if pub is None:
            return _erreur('Publicité introuvable.', status.HTTP_404_NOT_FOUND)
        type_affichage = request.data.get('type_affichage') or TypeAffichage.CARROUSEL
        if type_affichage not in TypeAffichage.values:
            return _erreur(f'Emplacement inconnu : {type_affichage}.')
        utilisateur = request.user if request.user.is_authenticated else None
        if not sp.enregistrer_impression(pub, utilisateur, request.data):
            return Response({'message': 'Impression déjà comptée.'}, status=status.HTTP_200_OK)
        return Response({'message': 'Impression enregistrée.'}, status=status.HTTP_201_CREATED)


class DecouvrirView(APIView):
    """GET decouvrir/ -> {actif, version, ecrans: [{id, ordre, titre, texte,
    image, bouton: {libelle, categorie} | null}]}. L'app le montre une fois
    au premier lancement, puis de nouveau quand `version` change.
    Bouton null si sa catégorie est devenue indisponible."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        params = ParametresPoufiret.obtenir()
        if not params.parcours_actif:
            return Response({'actif': False, 'version': params.version_parcours, 'ecrans': []})
        ecrans = list(sp.ecrans_actifs())
        accessibles = sp.categories_accessibles()
        cats = sp.categories_serialisees(
            [e.bouton_categorie_id for e in ecrans if e.bouton_categorie_id in accessibles], request)
        donnees = []
        for e in ecrans:
            bouton = None
            if e.bouton_libelle and e.bouton_categorie_id in cats:
                bouton = {'libelle': e.bouton_libelle, 'categorie': cats[e.bouton_categorie_id]}
            donnees.append({'id': str(e.id), 'ordre': e.ordre, 'titre': e.titre, 'texte': e.texte,
                            'image': request.build_absolute_uri(e.image.url) if e.image else None,
                            'bouton': bouton})
        return Response({'actif': True, 'version': params.version_parcours, 'ecrans': donnees})
