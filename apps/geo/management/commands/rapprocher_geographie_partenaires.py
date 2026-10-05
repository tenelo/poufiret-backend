"""Rapprochement des villes/quartiers texte des partenaires avec la géographie.

    python manage.py rapprocher_geographie_partenaires              # rapport seul
    python manage.py rapprocher_geographie_partenaires --appliquer  # écrit les « exact »
"""
from django.core.management.base import BaseCommand

from apps.geo.rapprochement import analyser, appliquer, compteurs, lignes_a_traiter
from apps.users.models import ProfilPartenaire


class Command(BaseCommand):
    help = 'Rapproche ville/quartier texte des partenaires avec la géographie (rapport par défaut).'

    def add_arguments(self, parser):
        parser.add_argument('--appliquer', action='store_true',
                            help='Écrit les correspondances « exact » (journalisées).')

    def handle(self, *args, **options):
        profils = list(ProfilPartenaire.objects
                       .select_related('departement', 'localite', 'quartier_geo', 'user')
                       .order_by('nom_commerce'))
        lignes, rapproches = lignes_a_traiter(profils)
        cpt = compteurs(lignes, rapproches)
        self.stdout.write(f"exact={cpt['exact']} proposition={cpt['proposition']} "
                          f"aucun={cpt['aucun']} rapproches={cpt['rapproches']}")

        for statut in ('exact', 'proposition', 'aucun'):
            selection = [l for l in lignes if l['statut'] == statut]
            if not selection:
                continue
            self.stdout.write(f'\n--- {statut} ({len(selection)}) ---')
            for l in selection:
                loc = l['localite']['nom'] if l['localite'] else '-'
                quart = l['quartier']['nom'] if l['quartier'] else '-'
                self.stdout.write(f"  id={l['partenaire_id']:<5} {l['nom'][:30]:<30} "
                                  f"ville='{l['ville_texte']}' quartier='{l['quartier_texte']}' "
                                  f"-> localite={loc} quartier={quart}")

        if not options['appliquer']:
            self.stdout.write(self.style.WARNING('Lecture seule : relancer avec --appliquer pour écrire les « exact ».'))
            return

        par_id = {p.id: p for p in profils}
        ecrits = 0
        for l in lignes:
            if l['statut'] != 'exact':
                continue
            localite = self._localite(l)
            quartier = self._quartier(l)
            if appliquer(par_id[l['partenaire_id']], localite, quartier,
                         acteur=None, motif='Rapprochement automatique (commande)') == {}:
                ecrits += 1
        self.stdout.write(self.style.SUCCESS(f'{ecrits} partenaire(s) rapproché(s).'))

    @staticmethod
    def _localite(ligne):
        from apps.geo.models import Localite
        return Localite.objects.get(pk=ligne['localite']['id'])

    @staticmethod
    def _quartier(ligne):
        from apps.geo.models import Quartier
        return Quartier.objects.get(pk=ligne['quartier']['id']) if ligne['quartier'] else None
