"""Crédits de formule publicitaire (geste commercial, réservé à EstAdmin).

Un crédit = une formule offerte à un partenaire sans paiement immédiat, en
attente d'être consommée (création d'une publicité). Contrairement à
`administration.faveurs` (qui offre directement une campagne active), ici
l'admin ne fait qu'accorder le droit ; la consommation elle-même (pose de
`publicite_consommatrice` + `statut=CONSOMME` + `consomme_le`, puis
activation de la pub) se fait côté partenaire, à la création de sa pub
(voir `consommer_credit` et apps.publicites.views.MesPublicitesView).

Chaque action est tracée dans JournalModeration via `_journaliser`
(audit commun avec apps.administration.faveurs), best-effort : l'import
et l'appel sont protégés pour ne jamais faire échouer l'opération métier
si l'API du helper venait à changer.
"""
from django.db import transaction
from django.utils import timezone

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


@transaction.atomic
def consommer_credit(partenaire, credit, publicite):
    """Consomme un crédit disponible pour activer `publicite` gratuitement.

    partenaire : ProfilPartenaire qui consomme (doit être le titulaire du
                 crédit).
    credit     : CreditFormulePub à consommer.
    publicite  : Publicite nouvellement créée par ce partenaire, portant
                 la MÊME formule que le crédit (pas de substitution de
                 formule via un crédit).

    Active la pub immédiatement (statut ACTIVE + dates de diffusion) en
    réutilisant `services.activer_publicite` — le même calcul de dates que
    la transition « valider » et que la faveur admin (`offrir_campagne`),
    jamais réinventé ici. La pub est aussi marquée comme faveur
    (`est_faveur`), cohérence avec offrir_campagne : c'est une campagne
    diffusée sans paiement direct, l'admin qui a accordé le crédit en est
    tracé comme l'accordant de la faveur.

    Lève ValueError si le crédit n'appartient pas au partenaire, n'est
    plus disponible, ou si sa formule ne correspond pas à celle de la pub.
    """
    from .services import activer_publicite

    if credit.partenaire_id != partenaire.id:
        raise ValueError("Ce crédit n'appartient pas à ce partenaire.")
    if credit.statut != CreditFormulePub.Statut.DISPONIBLE:
        raise ValueError('Ce crédit a déjà été consommé.')
    if credit.formule_id != publicite.formule_id:
        raise ValueError(
            'La formule du crédit ne correspond pas à celle de la publicité.')

    credit.statut = CreditFormulePub.Statut.CONSOMME
    credit.consomme_le = timezone.now()
    credit.publicite_consommatrice = publicite
    credit.save(update_fields=['statut', 'consomme_le', 'publicite_consommatrice'])

    activer_publicite(publicite)
    publicite.est_faveur = True
    publicite.faveur_accordee_par = credit.accorde_par
    publicite.faveur_motif = (
        'Crédit de formule consommé'
        + (f' — {credit.motif}' if credit.motif else '')
    )
    publicite.save(update_fields=['est_faveur', 'faveur_accordee_par', 'faveur_motif'])

    _journaliser_best_effort(
        partenaire.user, credit.accorde_par, 'consommer_credit_pub',
        f"Pub « {publicite.titre} » activée via crédit {credit.formule.nom}",
    )
    return publicite
