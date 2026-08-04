"""Octroi et retrait de faveurs (geste commercial, réservé à EstAdmin).

Une faveur = un plan payant offert à un partenaire sans paiement. On
réutilise le socle abonnement : on pose simplement `plan`, les dates, et
les champs de traçabilité `est_faveur` / `faveur_accordee_par` /
`faveur_motif`. La portée géographique suit automatiquement le plan
choisi (propriété `ProfilPartenaire.portee`).

L'expiration réutilise la durée du plan (`duree_jours`, -1 = illimité),
exactement comme un abonnement payant — pas de système parallèle.

Chaque action est tracée dans JournalModeration via `_journaliser`
(audit commun), en ciblant le compte User du partenaire.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.users.models import PlanAbonnement
from .models import JournalModeration
from .moderation import _journaliser


def _calcul_fin(debut, plan):
    """Date de fin depuis la durée du plan. -1 (illimité) => None."""
    if plan.duree_jours is not None and plan.duree_jours >= 0:
        return debut + timedelta(days=plan.duree_jours)
    return None


@transaction.atomic
def accorder_faveur(acteur, profil, plan, motif=''):
    """Offre `plan` au partenaire `profil` sans paiement.

    acteur : User admin qui accorde (tracé dans faveur_accordee_par + audit).
    profil : ProfilPartenaire cible.
    plan   : PlanAbonnement offert (porte la portée + la durée).
    motif  : raison libre (ex. "Partenariat", "Lancement").
    """
    debut = timezone.localdate()
    profil.plan = plan
    profil.abonnement_debut = debut
    profil.abonnement_fin = _calcul_fin(debut, plan)
    profil.est_faveur = True
    profil.faveur_accordee_par = acteur
    profil.faveur_motif = motif or ''
    profil.save(update_fields=[
        'plan', 'abonnement_debut', 'abonnement_fin',
        'est_faveur', 'faveur_accordee_par', 'faveur_motif',
    ])
    _journaliser(
        acteur, profil.user, JournalModeration.Action.ACCORDER_FAVEUR,
        f"{plan.libelle} — {motif}".strip(' —'),
    )
    return profil


@transaction.atomic
def retirer_faveur(acteur, profil, motif=''):
    """Retire la faveur : repasse au plan Basique et nettoie les champs.

    Le partenaire n'est pas suspendu — il perd juste les avantages offerts
    et revient au socle gratuit.
    """
    basique = PlanAbonnement.objects.filter(
        code=PlanAbonnement.Code.BASIQUE).first()
    profil.plan = basique or profil.plan
    profil.abonnement_debut = None
    profil.abonnement_fin = None
    profil.est_faveur = False
    profil.faveur_accordee_par = None
    profil.faveur_motif = ''
    profil.save(update_fields=[
        'plan', 'abonnement_debut', 'abonnement_fin',
        'est_faveur', 'faveur_accordee_par', 'faveur_motif',
    ])
    _journaliser(
        acteur, profil.user, JournalModeration.Action.RETIRER_FAVEUR,
        motif or '',
    )
    return profil
