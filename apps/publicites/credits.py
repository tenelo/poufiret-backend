"""Crédits de formule publicitaire (geste commercial, réservé à EstAdmin).

Un crédit = une formule offerte à un partenaire sans paiement immédiat, en
attente d'être consommée (création d'une publicité). Contrairement à
`administration.faveurs` (qui offre directement une campagne active), ici
l'admin ne fait qu'accorder le droit ; la consommation elle-même (pose de
`publicite_consommatrice` + `statut=CONSOMME` + `consomme_le`) se fera au
moment de la création de la pub, hors périmètre de ce module.

Chaque action est tracée dans JournalModeration via `_journaliser`
(audit commun avec apps.administration.faveurs), best-effort : l'import
et l'appel sont protégés pour ne jamais faire échouer l'opération métier
si l'API du helper venait à changer.
"""
from django.db import transaction

from .models import CreditFormulePub


def _journaliser_best_effort(acteur, cible, action, motif):
    """Best-effort : n'échoue jamais l'opération métier si le journal casse."""
    try:
        from apps.administration.moderation import _journaliser
        _journaliser(acteur, cible, action, motif)
    except Exception:
        pass


@transaction.atomic
def accorder_credit(acteur, partenaire, formule, motif=''):
    """Accorde un crédit de `formule` au partenaire `partenaire`.

    acteur    : User admin qui accorde (tracé dans accorde_par + audit).
    partenaire : ProfilPartenaire cible.
    formule   : FormulePublicite offerte (doit être active).
    motif     : raison libre (ex. "Compensation panne carrousel").

    Lève ValueError si la formule n'est plus active.
    """
    if not formule.est_active:
        raise ValueError("Cette formule n'est plus disponible.")

    credit = CreditFormulePub.objects.create(
        partenaire=partenaire,
        formule=formule,
        statut=CreditFormulePub.Statut.DISPONIBLE,
        accorde_par=acteur,
        motif=motif or '',
    )
    _journaliser_best_effort(
        acteur, partenaire.user, 'accorder_credit_pub',
        f"Crédit {formule.nom} — {motif}".strip(' —'),
    )
    return credit


@transaction.atomic
def retirer_credit(acteur, credit, motif=''):
    """Retire (supprime) un crédit encore disponible.

    acteur : User admin qui retire (tracé dans l'audit).
    credit : CreditFormulePub cible.
    motif  : raison libre.

    Lève ValueError si le crédit a déjà été consommé (il n'existe pas de
    statut « annulé » : un crédit disponible est simplement supprimé).
    """
    if credit.statut == CreditFormulePub.Statut.CONSOMME:
        raise ValueError('Ce crédit a déjà été consommé, impossible de le retirer.')

    partenaire_user = credit.partenaire.user
    formule_nom = credit.formule.nom
    _journaliser_best_effort(
        acteur, partenaire_user, 'retirer_credit_pub',
        f"Crédit {formule_nom} — {motif}".strip(' —'),
    )
    credit.delete()
