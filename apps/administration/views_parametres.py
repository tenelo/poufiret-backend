"""Menu « Paramètres » : dictionnaire de recherche (mots-clés, termes sans
résultat) et ordre d'affichage des catégories. Capacité gerer_parametres
(privilégiée). Toutes les écritures sont journalisées.
"""
from datetime import datetime

from django.db import transaction
from django.db.models import F
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Categorie, RechercheSansResultat, annoter_nb_partenaires
from apps.catalog.recherche import LONGUEUR_MOT_MAX, MOTS_MAX, normaliser_mots_cles, normaliser_terme, rechercher
from apps.core.permissions import ADroitDe

from .moderation import _journaliser
from .models import JournalModeration

_PERMISSION = [IsAuthenticated, ADroitDe('gerer_parametres')]
_STATUTS = ('a_traiter', 'traite', 'ignore')


def _parser_date(valeur):
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _erreur(champ, message, statut=400):
    return Response({'erreur': True, 'details': {champ: [message]}}, status=statut)


def _categorie_mots(c):
    return {'id': c.id, 'nom': c.nom, 'parent_id': c.parent_id, 'mots_cles': list(c.mots_cles or [])}


# ── Dictionnaire de recherche ────────────────────────────────────────

class RechercheCategoriesView(APIView):
    """GET /administration/parametres/recherche/categories/"""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = Categorie.objects.filter(est_archivee=False).order_by('ordre', 'nom')
        return Response({'resultats': [_categorie_mots(c) for c in qs]})


class RechercheCategorieDetailView(APIView):
    """PATCH /administration/parametres/recherche/categories/<id>/ {"mots_cles": [...]}"""
    permission_classes = _PERMISSION

    def patch(self, request, pk):
        categorie = Categorie.objects.filter(pk=pk, est_archivee=False).first()
        if categorie is None:
            return Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        if 'mots_cles' not in request.data:
            return _erreur('mots_cles', 'Champ obligatoire.')
        mots = normaliser_mots_cles(request.data.get('mots_cles'))
        if mots is None:
            return _erreur('mots_cles', f'Liste de textes attendue (max {MOTS_MAX} mots, '
                                        f'{LONGUEUR_MOT_MAX} caractères chacun).')
        categorie.mots_cles = mots
        categorie.save(update_fields=['mots_cles'])
        _journaliser(request.user, None, JournalModeration.Action.PARAM_MOTS_CLES,
                     f'« {categorie.nom} » : {len(mots)} mot(s)-clé(s)')
        return Response(_categorie_mots(categorie))


def _groupes_sans_resultat(qs):
    """Termes regroupés après normalisation, du plus demandé au moins demandé."""
    groupes = {}
    for r in qs.order_by('-nb_occurrences', '-vu_le'):
        g = groupes.setdefault(normaliser_terme(r.terme), {
            'rows': [], 'nb': 0, 'vu': None, 'statuts': set(), 'rep': r})
        g['rows'].append(r)
        g['nb'] += r.nb_occurrences
        g['vu'] = r.vu_le if g['vu'] is None or r.vu_le > g['vu'] else g['vu']
        g['statuts'].add(r.statut)
    for g in groupes.values():
        if 'a_traiter' in g['statuts']:
            g['statut'] = 'a_traiter'
        elif 'traite' in g['statuts']:
            g['statut'] = 'traite'
        else:
            g['statut'] = 'ignore'
    return sorted(groupes.items(), key=lambda kv: (-kv[1]['nb'], -kv[1]['vu'].timestamp()))


class RechercheSansResultatView(APIView):
    """GET /administration/parametres/recherche/sans-resultat/?statut=&du=&au="""
    permission_classes = _PERMISSION

    def get(self, request):
        p = request.query_params
        statut = p.get('statut', 'tous')
        if statut not in ('tous',) + _STATUTS:
            return Response({'erreur': True, 'message': f'Statut inconnu : {statut}.'}, status=400)
        du, au = p.get('du'), p.get('au')
        du_d, au_d = _parser_date(du), _parser_date(au)
        if (du and du_d is None) or (au and au_d is None):
            return Response({'erreur': True, 'message': 'Dates attendues au format AAAA-MM-JJ.'}, status=400)
        qs = RechercheSansResultat.objects.all()
        if du_d:
            qs = qs.filter(vu_le__date__gte=du_d)
        if au_d:
            qs = qs.filter(vu_le__date__lte=au_d)

        groupes = _groupes_sans_resultat(qs)
        compteurs = {s: sum(1 for _c, g in groupes if g['statut'] == s) for s in _STATUTS}
        resultats = [{
            'id': g['rep'].id,
            'terme': cle,
            'nb_recherches': g['nb'],
            'derniere_recherche': g['vu'].isoformat(),
            'statut': g['statut'],
        } for cle, g in groupes if statut in ('tous', g['statut'])]
        return Response({'resultats': resultats, 'compteurs': compteurs})


class TraiterSansResultatView(APIView):
    """POST /administration/parametres/recherche/sans-resultat/<id>/traiter/
    {"action": "ajouter_mot_cle", "categorie_id"} | {"action": "ignorer"}"""
    permission_classes = _PERMISSION

    def post(self, request, pk):
        ligne = RechercheSansResultat.objects.filter(pk=pk).first()
        if ligne is None:
            return Response({'erreur': True, 'message': 'Terme introuvable.'}, status=404)
        action = request.data.get('action')
        cle = normaliser_terme(ligne.terme)
        ids_groupe = [r.id for r in RechercheSansResultat.objects.all()
                      if normaliser_terme(r.terme) == cle]

        with transaction.atomic():
            if action == 'ajouter_mot_cle':
                try:
                    categorie = Categorie.objects.filter(
                        pk=int(request.data.get('categorie_id')), est_archivee=False).first()
                except (TypeError, ValueError):
                    categorie = None
                if categorie is None:
                    return _erreur('categorie_id', 'Catégorie introuvable.')
                mots = list(categorie.mots_cles or [])
                if cle not in mots:
                    mots.append(cle)
                categorie.mots_cles = normaliser_mots_cles(mots) or []
                categorie.save(update_fields=['mots_cles'])
                nouveau_statut = 'traite'
                action_journal = JournalModeration.Action.PARAM_RECHERCHE_TRAITE
                motif = f'« {cle} » ajouté aux mots-clés de « {categorie.nom} »'
            elif action == 'ignorer':
                categorie = None
                nouveau_statut = 'ignore'
                action_journal = JournalModeration.Action.PARAM_RECHERCHE_IGNORE
                motif = f'« {cle} » ignoré'
            else:
                return _erreur('action', 'Action inconnue : ajouter_mot_cle ou ignorer.')

            RechercheSansResultat.objects.filter(pk__in=ids_groupe).update(
                statut=nouveau_statut, traite=(nouveau_statut == 'traite'))
            _journaliser(request.user, None, action_journal, motif)

        return Response({
            'id': ligne.id, 'terme': cle, 'statut': nouveau_statut,
            'categorie': _categorie_mots(categorie) if categorie else None,
        })


class TesterRechercheView(APIView):
    """GET /administration/parametres/recherche/tester/?q= — même moteur que la
    recherche publique, sans journaliser la requête."""
    permission_classes = _PERMISSION

    def get(self, request):
        terme = (request.query_params.get('q') or '').strip()
        if len(terme) < 2:
            return Response({'categories': [], 'partenaires': [], 'articles': [], 'total': 0})
        donnees = rechercher(request, terme)
        categories = [{'id': c['id'], 'nom': c['nom']} for c in donnees['categories']]
        partenaires = [{'id': p['id'], 'nom': p['nom_commerce']} for p in donnees['partenaires']]
        articles = [{'id': a['id'], 'nom': a['nom']} for a in donnees['articles']]
        return Response({'categories': categories, 'partenaires': partenaires, 'articles': articles,
                         'total': len(categories) + len(partenaires) + len(articles)})


# ── Ordre et visibilité des catégories ───────────────────────────────

def _categorie_grille(c, request):
    image = c.image_couverture
    try:
        url = request.build_absolute_uri(image.url) if image else None
    except Exception:
        url = None
    return {
        'id': c.id, 'nom': c.nom, 'icone': c.icone, 'image': url, 'ordre': c.ordre,
        'est_active': c.est_active, 'parent_id': c.parent_id,
        'nb_partenaires': max(c.nb_via_liaison or 0, c.nb_via_articles or 0),
    }


class CategoriesParametresView(APIView):
    """GET /administration/parametres/categories/ — trié par parent puis ordre."""
    permission_classes = _PERMISSION

    def get(self, request):
        qs = annoter_nb_partenaires(Categorie.objects.filter(est_archivee=False)).order_by(
            F('parent_id').asc(nulls_first=True), 'ordre', 'nom')
        return Response({'resultats': [_categorie_grille(c, request) for c in qs]})


class OrdreCategoriesView(APIView):
    """POST /administration/parametres/categories/ordre/
    {"parent_id": null|id, "ordre": [id1, id2, …]} — ordre = 1..n sur ce niveau.
    Les catégories du niveau absentes de la liste gardent leur ordre relatif, à la suite."""
    permission_classes = _PERMISSION

    def post(self, request):
        parent_id = request.data.get('parent_id')
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                return _erreur('parent_id', 'Identifiant attendu ou null.')
            if not Categorie.objects.filter(pk=parent_id, est_archivee=False).exists():
                return _erreur('parent_id', 'Catégorie parente introuvable.', 404)
        ids = request.data.get('ordre')
        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            return _erreur('ordre', 'Liste d\'identifiants attendue.')
        if len(set(ids)) != len(ids):
            return _erreur('ordre', 'Identifiant en double.')

        niveau = Categorie.objects.filter(est_archivee=False, parent_id=parent_id) if parent_id is not None \
            else Categorie.objects.filter(est_archivee=False, parent__isnull=True)
        ids_niveau = set(niveau.values_list('id', flat=True))
        hors = [i for i in ids if i not in ids_niveau]
        if hors:
            return _erreur('ordre', f'Catégorie(s) absente(s) de ce niveau : {hors}.')

        reste = [i for i in niveau.order_by('ordre', 'nom').values_list('id', flat=True) if i not in ids]
        ordonnees = ids + reste
        with transaction.atomic():
            for rang, cid in enumerate(ordonnees, start=1):
                Categorie.objects.filter(pk=cid).update(ordre=rang)
            _journaliser(request.user, None, JournalModeration.Action.PARAM_ORDRE_CATEG,
                         f'Niveau parent={parent_id} : {len(ordonnees)} catégorie(s) réordonnée(s)')
        return Response({'parent_id': parent_id, 'ordre': ordonnees})


class VisibiliteCategorieView(APIView):
    """PATCH /administration/parametres/categories/<id>/ {"est_active": bool}"""
    permission_classes = _PERMISSION

    def patch(self, request, pk):
        categorie = Categorie.objects.filter(pk=pk, est_archivee=False).first()
        if categorie is None:
            return Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        if 'est_active' not in request.data or not isinstance(request.data['est_active'], bool):
            return _erreur('est_active', 'Booléen attendu.')
        categorie.est_active = request.data['est_active']
        categorie.save(update_fields=['est_active'])
        _journaliser(request.user, None, JournalModeration.Action.PARAM_CATEG_VISIB,
                     f'« {categorie.nom} » : {"affichée" if categorie.est_active else "masquée"}')
        return Response(_categorie_grille(annoter_nb_partenaires(
            Categorie.objects.filter(pk=categorie.pk)).get(), request))
