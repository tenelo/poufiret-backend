"""Règles des pubs Poufiret (pubs maison du carrousel) et du parcours
« Découvrir Poufiret » : catégorie cible accessible, sélection et portée,
placement dans le carrousel, journalisation des affichages et clics, stats.
"""
from django.db.models import Count, F, Q
from django.utils import timezone

from .models import (EcranDecouverte, ImpressionPubPoufiret, ParametresPoufiret,
                     PubPoufiret, TypeAffichage)


# ── Catégorie cible ──────────────────────────────────────────────────────

def categories_accessibles():
    """Ids des catégories ouvrables dans l'app : active, non archivée, et
    tous ses parents aussi. Une requête (table des catégories, petite)."""
    from apps.catalog.models import Categorie
    lignes = {pk: (parent, actif and not archive) for pk, parent, actif, archive in
              Categorie.objects.values_list('id', 'parent_id', 'est_active', 'est_archivee')}
    accessibles = set()
    for pk in lignes:
        courant, vus, ok = pk, set(), True
        while courant is not None and courant not in vus:
            vus.add(courant)
            parent, utilisable = lignes.get(courant, (None, False))
            if not utilisable:
                ok = False
                break
            courant = parent
        if ok:
            accessibles.add(pk)
    return accessibles


def raison_categorie_invalide(categorie):
    """Message (400) si la catégorie ne peut pas être ciblée, sinon None."""
    if categorie is None:
        return 'Catégorie cible obligatoire.'
    if categorie.est_archivee:
        return f'La catégorie « {categorie.nom} » est archivée.'
    if not categorie.est_active:
        return f'La catégorie « {categorie.nom} » est désactivée (« Bientôt disponible »).'
    if categorie.pk not in categories_accessibles():
        return (f'La catégorie « {categorie.nom} » est inaccessible : '
                'une catégorie parente est désactivée ou archivée.')
    return None


def categories_serialisees(ids, request):
    """{id: objet catégorie} identique à une tuile de la grille de l'accueil
    (CategorieSerializer, mêmes annotations et sous-catégories)."""
    from apps.catalog.models import Categorie, annoter_nb_partenaires, prefetch_enfants_actifs
    from apps.catalog.serializers import CategorieSerializer
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    qs = annoter_nb_partenaires(Categorie.objects.filter(pk__in=ids)).prefetch_related(
        prefetch_enfants_actifs())
    return {c.pk: CategorieSerializer(c, context={'request': request}).data for c in qs}


# ── Sélection pour le carrousel ─────────────────────────────────────────

def _visible_pour(pub, utilisateur):
    """Même logique que les pubs partenaires : utilisateur anonyme ou sans
    département -> voit tout ; sinon région ou département de la pub."""
    dep_user = getattr(utilisateur, 'departement', None) if (
        utilisateur is not None and utilisateur.is_authenticated) else None
    if dep_user is None or pub.portee == PubPoufiret.Portee.TOUT:
        return True
    if pub.portee == PubPoufiret.Portee.REGION:
        return pub.region_id is None or pub.region_id == dep_user.region_id
    return pub.departement_id is None or pub.departement_id == dep_user.id


def pubs_maison_a_diffuser(utilisateur, params=None):
    """Pubs Poufiret à montrer maintenant à cet utilisateur, rotation
    équitable : la moins affichée aujourd'hui d'abord (pour cet utilisateur,
    ou au global s'il est anonyme), puis l'ordre réglé par l'admin.
    Indépendant du flag publicite_active : piloté par pubs_maison_actives."""
    params = params or ParametresPoufiret.obtenir()
    if not params.pubs_maison_actives:
        return []
    maintenant = timezone.now()
    candidates = (PubPoufiret.objects.filter(est_active=True, categorie__isnull=False)
                  .filter(Q(date_debut__isnull=True) | Q(date_debut__lte=maintenant))
                  .filter(Q(date_fin__isnull=True) | Q(date_fin__gt=maintenant)))
    accessibles = categories_accessibles()
    pubs = [p for p in candidates if p.categorie_id in accessibles and _visible_pour(p, utilisateur)]
    if not pubs:
        return []
    connecte = utilisateur is not None and utilisateur.is_authenticated
    vues = ImpressionPubPoufiret.objects.filter(
        pub__in=pubs, cree_le__date=timezone.localdate(), cliquee=False)
    if connecte:
        vues = vues.filter(utilisateur=utilisateur)
    nb = dict(vues.values_list('pub_id').annotate(n=Count('id')).order_by())
    pubs.sort(key=lambda p: (nb.get(p.pk, 0), p.ordre, p.cree_le))
    return pubs


def melanger(partenaires, maisons, frequence):
    """Une pub maison après chaque bloc de `frequence` pubs partenaires ;
    une seule à la fin si 0 < k < N ; seulement les pubs maison si k = 0 ;
    jamais deux fois la même pub maison."""
    if not partenaires:
        return list(maisons)
    n = max(1, frequence)
    reste = iter(maisons)
    resultat = []
    for i, p in enumerate(partenaires, start=1):
        resultat.append(p)
        if i % n == 0:
            m = next(reste, None)
            if m is not None:
                resultat.append(m)
    if len(partenaires) < n:
        m = next(reste, None)
        if m is not None:
            resultat.append(m)
    return resultat


def element_maison(pub, categorie, params, request):
    image = request.build_absolute_uri(pub.image_couverture.url) if pub.image_couverture else None
    return {
        'type': 'poufiret',
        'id': str(pub.id),
        'titre': pub.titre,
        'texte': pub.texte,
        'image_couverture': image,
        'duree_affichage_secondes': params.duree_affichage_secondes,
        'categorie': categorie,
    }


def elements_carrousel(publicites_serialisees, utilisateur, request):
    """Clé `elements` du carrousel : pubs partenaires (mêmes champs que
    `publicites`, + type) mélangées aux pubs Poufiret."""
    params = ParametresPoufiret.obtenir()
    maisons = pubs_maison_a_diffuser(utilisateur, params)
    cats = categories_serialisees([p.categorie_id for p in maisons], request)
    return melanger(
        [{'type': 'partenaire', **d} for d in publicites_serialisees],
        [element_maison(p, cats.get(p.categorie_id), params, request) for p in maisons],
        params.frequence_pub_maison)


# ── Journalisation (même logique que EnregistrerImpressionView) ─────────

def enregistrer_impression(pub, utilisateur, donnees):
    """Retourne True si enregistrée, False si affichage déjà compté dans
    cette session. Personne touchée comptée une seule fois, tous
    emplacements confondus ; un clic est toujours enregistré."""
    brut = donnees.get('cliquee', False)
    cliquee = brut if isinstance(brut, bool) else str(brut).strip().lower() in ('1', 'true', 'oui', 'yes')
    type_affichage = donnees.get('type_affichage') or TypeAffichage.CARROUSEL
    deja_vue = bool(utilisateur) and ImpressionPubPoufiret.objects.filter(
        pub=pub, utilisateur=utilisateur).exists()
    session = None
    if donnees.get('session_id'):
        from apps.analytics.models import TempsSessionUtilisateur
        try:
            session = TempsSessionUtilisateur.objects.filter(pk=donnees.get('session_id')).first()
        except Exception:
            session = None
    if session is not None and not cliquee and ImpressionPubPoufiret.objects.filter(
            pub=pub, session=session, type_affichage=type_affichage, cliquee=False).exists():
        return False
    minute = donnees.get('minute_session')
    try:
        minute = int(minute) if minute not in (None, '') else None
    except (TypeError, ValueError):
        minute = None
    ImpressionPubPoufiret.objects.create(pub=pub, utilisateur=utilisateur, type_affichage=type_affichage,
                                         minute_session=minute, session=session, cliquee=cliquee)
    maj = {'nb_impressions': F('nb_impressions') + 1}
    if utilisateur and not deja_vue:
        maj['nb_personnes_touchees'] = F('nb_personnes_touchees') + 1
    if cliquee:
        maj['nb_clics'] = F('nb_clics') + 1
    PubPoufiret.objects.filter(pk=pub.pk).update(**maj)
    return True


# ── Stats ───────────────────────────────────────────────────────────────

def taux_clic(clics, impressions):
    return round(clics / impressions * 100, 2) if impressions else 0


def impressions_par_type(ids):
    """{pub_id: {emplacement: n}} en une requête."""
    par_pub = {pk: {} for pk in ids}
    if par_pub:
        for pub_id, t, n in (ImpressionPubPoufiret.objects.filter(pub_id__in=list(par_pub))
                             .values_list('pub_id', 'type_affichage').annotate(n=Count('id')).order_by()):
            par_pub[pub_id][t] = n
    return par_pub


def stats_pub(pub, par_type=None):
    """Mêmes noms que les stats des pubs partenaires (_stats_pub)."""
    if par_type is None:
        par_type = impressions_par_type([pub.pk])[pub.pk]
    return {
        'nb_impressions': pub.nb_impressions,
        'nb_clics': pub.nb_clics,
        'taux_clic': taux_clic(pub.nb_clics, pub.nb_impressions),
        'nb_personnes_touchees': pub.nb_personnes_touchees,
        'impressions_par_type': par_type,
    }


# ── Parcours ────────────────────────────────────────────────────────────

def ecrans_actifs():
    return EcranDecouverte.objects.filter(est_actif=True).order_by('ordre', 'cree_le')


def raison_refus_parcours():
    """Message (400) si le parcours ne peut pas être publié ou activé."""
    n = ecrans_actifs().count()
    mini, maxi = ParametresPoufiret.NB_ECRANS_MIN, ParametresPoufiret.NB_ECRANS_MAX
    if not mini <= n <= maxi:
        return (f'Le parcours doit compter entre {mini} et {maxi} écrans actifs '
                f'(actuellement {n}).')
    return None
