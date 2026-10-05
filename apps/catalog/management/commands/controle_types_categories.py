"""Contrôle : partenaires dont le type a une catégorie correspondante qu'ils
n'ont pas. Lecture seule par défaut ; --corriger les rattache.

    python manage.py controle_types_categories
    python manage.py controle_types_categories --corriger
"""
from django.core.management.base import BaseCommand

from apps.catalog.correspondances import appliquer_correspondance, categories_manquantes


class Command(BaseCommand):
    help = 'Liste (ou corrige avec --corriger) les partenaires sans leur catégorie de type.'

    def add_arguments(self, parser):
        parser.add_argument('--corriger', action='store_true',
                            help='Ajoute la catégorie manquante à chaque partenaire.')

    def handle(self, *args, **options):
        manquants = categories_manquantes()
        if not manquants:
            self.stdout.write(self.style.SUCCESS('Aucun partenaire sans catégorie de type.'))
            return

        self.stdout.write(f'{len(manquants)} rattachement(s) manquant(s) :')
        self.stdout.write(f'{"id":>6}  {"partenaire":<30} {"type":<14} catégorie manquante')
        for partenaire, categorie in manquants:
            self.stdout.write(
                f'{partenaire.id:>6}  {partenaire.nom_commerce[:30]:<30} '
                f'{partenaire.type_partenaire:<14} {categorie.nom} (id={categorie.id})')

        if not options['corriger']:
            self.stdout.write(self.style.WARNING('Lecture seule : relancer avec --corriger pour rattacher.'))
            return

        partenaires_vus = {}
        for partenaire, _categorie in manquants:
            partenaires_vus.setdefault(partenaire.id, partenaire)
        crees = sum(len(appliquer_correspondance(p)) for p in partenaires_vus.values())
        self.stdout.write(self.style.SUCCESS(f'{crees} rattachement(s) créé(s).'))
