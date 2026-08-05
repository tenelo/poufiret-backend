"""Traitement des demandes de partenariat (accepter / rejeter).

Une demande arrive via /auth/devenir-partenaire/ : un ProfilPartenaire
est créé en statut EN_ATTENTE. Ici on tranche : acceptation (le partenaire
devient actif et visible) ou rejet (statut REJETE, vitrine masquée, motif
conservé). Chaque décision est tracée dans JournalModeration.
"""
from django.db import transaction

from apps.users.models import ProfilPartenaire
from .models import JournalModeration
from .moderation import _journaliser


@transaction.atomic
def accepter_partenaire(acteur, profil, motif=''):
    """Valide la demande : le partenaire devient actif et visible."""
    profil.statut = ProfilPartenaire.Statut.ACTIF
    profil.est_visible = True
    profil.save(update_fields=['statut', 'est_visible'])
    _journaliser(
        acteur, profil.user,
        JournalModeration.Action.ACCEPTER_PARTENAIRE, motif or '')
    return profil


@transaction.atomic
def rejeter_partenaire(acteur, profil, motif=''):
    """Rejette la demande : statut REJETE, vitrine masquée, motif conservé."""
    profil.statut = ProfilPartenaire.Statut.REJETE
    profil.est_visible = False
    if motif:
        profil.notes_admin = (profil.notes_admin + f"\n[Rejet] {motif}").strip()
    profil.save(update_fields=['statut', 'est_visible', 'notes_admin'])
    _journaliser(
        acteur, profil.user,
        JournalModeration.Action.REJETER_PARTENAIRE, motif or '')
    return profil
