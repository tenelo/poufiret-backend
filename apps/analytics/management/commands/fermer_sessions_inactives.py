"""Ferme les sessions analytics 'fantômes' : marquées actives mais dont le
dernier ping est trop ancien (app tuée, batterie, réseau coupé…).

Idempotente : peut tourner en boucle (cron) sans effet de bord. Ne touche
pas aux compteurs (déjà justes, car ils filtrent sur dernier_ping), c'est
juste de l'hygiène de base.

Usage :
    python manage.py fermer_sessions_inactives
    python manage.py fermer_sessions_inactives --seuil 300   # forcer 300s
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.analytics.models import TempsSessionUtilisateur, ParametresAnalytics


class Command(BaseCommand):
    help = "Ferme les sessions actives dont le dernier ping dépasse le seuil."

    def add_arguments(self, parser):
        parser.add_argument(
            '--seuil', type=int, default=None,
            help="Seuil en secondes (défaut : ParametresAnalytics).")

    def handle(self, *args, **options):
        seuil = options['seuil']
        if seuil is None:
            seuil = ParametresAnalytics.obtenir().seuil_en_ligne_secondes
        limite = timezone.now() - timedelta(seconds=seuil)

        fantomes = TempsSessionUtilisateur.objects.filter(
            est_active=True, dernier_ping__lt=limite)
        n = fantomes.update(est_active=False)
        self.stdout.write(self.style.SUCCESS(
            f"{n} session(s) fantôme(s) fermée(s) (seuil {seuil}s)."))
