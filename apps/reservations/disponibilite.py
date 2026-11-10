"""Occupation des véhicules et des hébergements — calcul UNIQUE.

Sémantique des dates (celle déjà en place dans le code, conservée) : une
réservation [date_debut, date_fin] occupe les jours J tels que
date_debut <= J < date_fin.
- Véhicule : date_fin = jour de restitution, libre pour une nouvelle prise en
  charge le même jour ; jours facturés = date_fin − date_debut.
- Hébergement : date_fin = jour de départ, libre (une nuit = son jour d'arrivée).

Seules les demandes de nature « réservation » au statut CONFIRMÉE occupent le
bien (une demande nouvelle / en cours de traitement ne bloque rien ;
terminée, annulée et refusée libèrent les dates). Véhicule : 1 unité ;
hébergement : Hebergement.nb_unites (défaut 1), une demande occupe son
nb_unites. Les logements (maisons : visite / achat) ne sont pas concernés.

Cache court (60 s) de l'état public, invalidé à chaque enregistrement d'une
demande de l'objet et à chaque modification de la fiche (signaux, voir
apps.reservations.signals).
"""
from datetime import timedelta

from django.core.cache import cache

from .models import DemandeReservation

STATUTS_OCCUPANTS = (DemandeReservation.Statut.CONFIRMEE,)
STATUTS_EN_ATTENTE = (DemandeReservation.Statut.NOUVELLE, DemandeReservation.Statut.EN_COURS)
DUREE_DEFAUT_JOURS = 180
DUREE_MAX_JOURS = 366
DUREE_CACHE_SECONDES = 60
MESSAGE_INDISPONIBLE = 'Ces dates ne sont plus disponibles.'
RAISON_REFUS_AUTOMATIQUE = 'Dates déjà réservées'


def fiche_occupable(objet):
    """Fiche véhicule ou hébergement de l'Article, sinon None (non concerné)."""
    if objet.type == objet.Type.VEHICULE:
        return getattr(objet, 'vehicule', None)
    if objet.type == objet.Type.HEBERGEMENT:
        return getattr(objet, 'hebergement', None)
    return None


def unites_total(fiche):
    """1 pour un véhicule ; nb_unites (≥ 1) pour un hébergement."""
    return max(getattr(fiche, 'nb_unites', 1) or 1, 1)


def jours(debut, fin):
    """Jours de [debut, fin[."""
    j = debut
    while j < fin:
        yield j
        j += timedelta(days=1)


def occupation_par_jour(objet_id, debut, fin, exclure_id=None):
    """{jour: unités occupées} sur [debut, fin[ (jours occupés seulement), à
    partir des demandes confirmées qui chevauchent la période. Une requête."""
    qs = DemandeReservation.objects.filter(
        objet_id=objet_id, nature=DemandeReservation.Nature.RESERVATION, statut__in=STATUTS_OCCUPANTS,
        date_debut__lt=fin, date_fin__gt=debut)
    if exclure_id:
        qs = qs.exclude(pk=exclure_id)
    occupation = {}
    for d_debut, d_fin, nb in qs.values_list('date_debut', 'date_fin', 'nb_unites'):
        for j in jours(max(d_debut, debut), min(d_fin, fin)):
            occupation[j] = occupation.get(j, 0) + (nb or 1)
    return occupation


def jours_insuffisants(fiche, debut, fin, nb_unites=1, exclure_id=None):
    """Jours de [debut, fin[ où il ne reste pas nb_unites unités (triés)."""
    total = unites_total(fiche)
    occupation = occupation_par_jour(fiche.article_id, debut, fin, exclure_id)
    return [j for j in jours(debut, fin) if occupation.get(j, 0) + nb_unites > total]


def _version(objet_id):
    return cache.get(f'dispo:v:{objet_id}', 0)


def invalider(objet_id):
    """Nouvelle version des disponibilités de l'objet (les entrées en cache
    deviennent inaccessibles et expirent d'elles-mêmes)."""
    try:
        cache.set(f'dispo:v:{objet_id}', _version(objet_id) + 1, None)
    except Exception:  # cache indisponible : jamais bloquant
        pass


def etat_disponibilites(fiche, du, au):
    """État public sur les jours [du, au] (bornes incluses) :
    {unites_total, jours_complets, unites_restantes (jours partiels seulement)}.
    Bien indisponible (fiche.disponibilite) : tous les jours complets."""
    cle = f'dispo:{fiche.article_id}:{_version(fiche.article_id)}:{du}:{au}'
    try:
        en_cache = cache.get(cle)
    except Exception:
        en_cache = None
    if en_cache is not None:
        return en_cache
    total = unites_total(fiche)
    fin = au + timedelta(days=1)
    if fiche.disponibilite != fiche.Disponibilite.DISPONIBLE:
        complets, restantes = [str(j) for j in jours(du, fin)], {}
    else:
        occupation = occupation_par_jour(fiche.article_id, du, fin)
        complets = [str(j) for j in jours(du, fin) if occupation.get(j, 0) >= total]
        restantes = {str(j): total - n for j, n in sorted(occupation.items()) if 0 < n < total}
    etat = {'unites_total': total, 'jours_complets': complets, 'unites_restantes': restantes}
    try:
        cache.set(cle, etat, DUREE_CACHE_SECONDES)
    except Exception:
        pass
    return etat


def demandes_a_refuser(demande):
    """Après la confirmation de `demande` : les AUTRES demandes en attente
    (nouvelle, en cours) du même objet qui n'ont plus assez d'unités."""
    fiche = fiche_occupable(demande.objet)
    if fiche is None:
        return []
    candidates = (DemandeReservation.objects
                  .filter(objet_id=demande.objet_id, nature=DemandeReservation.Nature.RESERVATION,
                          statut__in=STATUTS_EN_ATTENTE,
                          date_debut__lt=demande.date_fin, date_fin__gt=demande.date_debut)
                  .exclude(pk=demande.pk).select_related('client', 'partenaire__user', 'objet'))
    return [d for d in candidates
            if d.date_debut and d.date_fin
            and jours_insuffisants(fiche, d.date_debut, d.date_fin, d.nb_unites or 1, exclure_id=d.pk)]
