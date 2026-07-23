"""Clot les publicites dont la diffusion est terminee.

A lancer periodiquement (cron) :
    python manage.py cloturer_publicites

Une pub est cloturee si sa date de fin est passee ET que sa garantie de
couverture (cible % de clients actifs) est atteinte. Sinon elle reste
diffusee : c'est la promesse vendue avec les formules a garantie.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.publicites.models import Publicite


class Command(BaseCommand):
    help = "Termine les publicites dont la periode de diffusion est ecoulee."

    def add_arguments(self, parseur):
        parseur.add_argument(
            '--simulation', action='store_true',
            help="Affiche ce qui serait fait, sans rien modifier.",
        )

    def handle(self, *args, **options):
        simulation = options['simulation']
        maintenant = timezone.now()

        candidates = (
            Publicite.objects
            .filter(statut=Publicite.Statut.ACTIVE,
                    fin_diffusion__lte=maintenant)
            .select_related('formule', 'partenaire')
        )

        cloturees, prolongees = 0, 0
        for pub in candidates:
            if not pub.cible_atteinte:
                prolongees += 1
                self.stdout.write(
                    f'  prolongee (garantie non atteinte) : {pub.titre}')
                continue
            if not simulation:
                pub.statut = Publicite.Statut.TERMINEE
                pub.save(update_fields=['statut', 'modifie_le'])
            cloturees += 1
            self.stdout.write(self.style.SUCCESS(f'  terminee : {pub.titre}'))

        prefixe = '[SIMULATION] ' if simulation else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefixe}{cloturees} cloturee(s), {prolongees} prolongee(s).'))
