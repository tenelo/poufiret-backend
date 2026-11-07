"""Règles métier des avis clients (apps.social.models.Avis).

- Seul le client de l'objet peut le noter, et seulement s'il est dans son
  statut final positif : commande livrée, course livrée, intervention
  terminée, réservation terminée.
- Un avis par (auteur, objet) ; modifiable 7 jours après sa création.
- La note moyenne / le nombre d'avis du partenaire (avis visibles) sont
  recalculés à chaque création, modification ou masquage.
Refus : ErreurMetier (message clair, 400 / 403 / 404 / 409).
"""
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg, Count
from django.utils import timezone

from apps.core.exceptions import ErreurMetier

DELAI_MODIFICATION = timedelta(days=7)


def _definitions():
    """objet_type → (modèle, champ client, statut final positif, libellé)."""
    from apps.livraison.models import Course
    from apps.messaging.models import DemandeIntervention
    from apps.orders.models import Commande
    from apps.reservations.models import DemandeReservation
    return {
        'commande': (Commande, 'user_id', 'livree', 'la commande livrée'),
        'course': (Course, 'demandeur_id', 'livree', 'la course livrée'),
        'intervention': (DemandeIntervention, 'user_id', 'terminee', "l'intervention terminée"),
        'reservation': (DemandeReservation, 'client_id', 'terminee', 'la réservation terminée'),
    }


def charger_objet(objet_type, objet_id):
    """L'objet noté, ou ErreurMetier (type inconnu → 400, introuvable → 404)."""
    definitions = _definitions()
    if objet_type not in definitions:
        raise ErreurMetier("Type d'objet invalide (commande, course, intervention ou reservation).",
                           {'objet_type': list(definitions)})
    modele = definitions[objet_type][0]
    try:
        objet = modele.objects.filter(pk=objet_id).first()
    except (ValueError, TypeError, DjangoValidationError):  # id mal formé (entier / UUID)
        objet = None
    if objet is None:
        raise ErreurMetier(f'{objet_type.capitalize()} introuvable.', status_code=404)
    return objet


def cibles(objet_type, objet):
    """(partenaire, livreur) notés pour cet objet."""
    if objet_type == 'course':
        partenaire = objet.commande.partenaire if objet.commande_id else None
        return partenaire, objet.livreur
    if objet_type == 'intervention':
        return objet.artisan, None
    return objet.partenaire, None


def raison_refus(user, objet_type, objet):
    """None si `user` peut noter cet objet (hors unicité), sinon (message, code HTTP)."""
    _modele, champ_client, statut_final, libelle = _definitions()[objet_type]
    if getattr(objet, champ_client) != getattr(user, 'id', None):
        return ('Seul le client peut noter cet élément.', 403)
    if objet.statut != statut_final:
        return (f'Vous pourrez donner votre avis une fois {libelle} '
                f'(statut actuel : {objet.get_statut_display()}).', 400)
    return None


def etat_notation(user, objet_type, objet):
    """{'peut_noter', 'mon_avis'} pour le détail client d'un objet : peut_noter
    = client, statut final positif et pas encore d'avis ; mon_avis = id ou null."""
    from .models import Avis
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'peut_noter': False, 'mon_avis': None}
    mon_avis = (Avis.objects.filter(auteur=user, objet_type=objet_type, objet_id=str(objet.pk))
                .values_list('id', flat=True).first())
    return {'peut_noter': mon_avis is None and raison_refus(user, objet_type, objet) is None,
            'mon_avis': mon_avis}


def etats_notation(user, objet_type, objets):
    """Même chose pour une liste (une seule requête sur les avis) : {pk: état}."""
    from .models import Avis
    if user is None or not getattr(user, 'is_authenticated', False):
        return {o.pk: {'peut_noter': False, 'mon_avis': None} for o in objets}
    avis = dict(Avis.objects.filter(auteur=user, objet_type=objet_type,
                                    objet_id__in=[str(o.pk) for o in objets])
                .values_list('objet_id', 'id'))
    return {o.pk: {'mon_avis': avis.get(str(o.pk)),
                   'peut_noter': str(o.pk) not in avis and raison_refus(user, objet_type, o) is None}
            for o in objets}


def recalculer_note_partenaire(partenaire_id):
    """note_moyenne (2 décimales, null sans avis) et nb_avis : avis visibles."""
    if not partenaire_id:
        return
    from apps.users.models import ProfilPartenaire

    from .models import Avis
    agregat = Avis.objects.filter(partenaire_id=partenaire_id, est_visible=True).aggregate(
        moyenne=Avg('note'), nb=Count('id'))
    moyenne = round(agregat['moyenne'], 2) if agregat['moyenne'] is not None else None
    ProfilPartenaire.objects.filter(pk=partenaire_id).update(note_moyenne=moyenne, nb_avis=agregat['nb'])


def modifiable_jusqu_au(avis):
    return avis.cree_le + DELAI_MODIFICATION


def verifier_modifiable(avis, user):
    if avis.auteur_id != getattr(user, 'id', None):
        raise ErreurMetier('Vous ne pouvez modifier que vos propres avis.', status_code=403)
    if timezone.now() > modifiable_jusqu_au(avis):
        raise ErreurMetier("Cet avis n'est plus modifiable (7 jours après sa publication).")
