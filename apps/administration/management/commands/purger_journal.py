"""Purge du journal d'audit (JournalModeration) au-delà d'une durée.

Sans --appliquer : rapport seul (rien n'est supprimé). Une entrée est
purgeable si sa DERNIÈRE occurrence (derniere_occurrence, sinon cree_le)
est plus ancienne que --jours.

Usage :
    python manage.py purger_journal                 # rapport, 365 jours
    python manage.py purger_journal --jours=180
    python manage.py purger_journal --jours=365 --appliquer
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from apps.administration.models import JournalModeration


class Command(BaseCommand):
    help = "Purge le journal d'audit au-delà de --jours (rapport seul sans --appliquer)."

    def add_arguments(self, parser):
        parser.add_argument('--jours', type=int, default=365,
                            help='Conservation en jours (défaut : 365).')
        parser.add_argument('--appliquer', action='store_true',
                            help='Supprime réellement (sinon : simulation).')

    def handle(self, *args, **options):
        jours = options['jours']
        if jours < 1:
            self.stderr.write(self.style.ERROR('--jours doit être >= 1.'))
            return
        limite = timezone.now() - timedelta(days=jours)
        anciennes = JournalModeration.objects.filter(
            Q(derniere_occurrence__lt=limite)
            | Q(derniere_occurrence__isnull=True, cree_le__lt=limite))

        total = JournalModeration.objects.count()
        resume = anciennes.aggregate(n=Count('id'), occurrences=Sum('occurrences'),
                                     plus_ancienne=Min('cree_le'))
        self.stdout.write(f"Journal : {total} entrée(s) au total.")
        self.stdout.write(
            f"Plus anciennes que {jours} j (avant le {timezone.localtime(limite):%d/%m/%Y}) : "
            f"{resume['n']} entrée(s), {resume['occurrences'] or 0} occurrence(s), "
            f"la plus ancienne du {timezone.localtime(resume['plus_ancienne']):%d/%m/%Y}"
            if resume['n'] else
            f"Aucune entrée plus ancienne que {jours} j.")
        for ligne in (anciennes.order_by().values('action').annotate(n=Count('id')).order_by('-n')):
            self.stdout.write(f"  - {ligne['action']} : {ligne['n']}")

        if not options['appliquer']:
            self.stdout.write(self.style.WARNING(
                'Simulation : rien supprimé (ajouter --appliquer pour purger).'))
            return
        n, _detail = anciennes.delete()
        self.stdout.write(self.style.SUCCESS(f'{n} entrée(s) supprimée(s).'))
