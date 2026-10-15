"""Rapport de taille des tables PostgreSQL (LECTURE SEULE, ne supprime rien).

Les N tables les plus lourdes (pg_total_relation_size : données + index +
TOAST), leur nombre de lignes (exact) et une proposition de conservation.

Usage :
    python manage.py rapport_tables            # top 10
    python manage.py rapport_tables --top=20
    python manage.py rapport_tables --markdown # tableau à coller dans un rapport
"""
from django.core.management.base import BaseCommand
from django.db import connection

# Propositions de conservation (aucune n'est appliquée automatiquement).
PROPOSITIONS = {
    'analytics_tempssessionutilisateur':
        'Sessions analytics : agréger par jour au-delà de 90 j, supprimer le détail > 180 j.',
    'analytics_profilnavigation':
        'Profil de navigation : garder 180 j de détail, au-delà agrégats mensuels.',
    'analytics_vuevitrine':
        'Vues de vitrine : agréger par jour/partenaire au-delà de 90 j, détail purgé > 365 j.',
    'analytics_vueservicelivraison':
        'Vues service livraison : agréger par jour au-delà de 90 j, détail purgé > 365 j.',
    'catalog_vuearticle':
        'Vues d\'articles : agréger (nb_vues est déjà sur l\'article) et purger le détail > 180 j.',
    'catalog_recherchesansresultat':
        'Termes sans résultat : purger les lignes traitées/ignorées > 180 j.',
    'moderation_notification':
        'Notifications : supprimer les lues > 90 j et toutes celles > 365 j.',
    'administration_journalmoderation':
        'Journal d\'audit : 365 j (purger_journal --jours=365 --appliquer), regroupement actif.',
    'users_sessionappareil':
        'Sessions appareils : supprimer les révoquées/inactives sans activité depuis 180 j.',
    'users_codeotp':
        'Codes OTP : supprimer les codes expirés ou consommés > 30 j.',
    'token_blacklist_outstandingtoken':
        'Jetons JWT : flushexpiredtokens (commande simplejwt) chaque nuit.',
    'token_blacklist_blacklistedtoken':
        'Jetons blacklistés : purgés avec flushexpiredtokens (cascade).',
    'django_session':
        'Sessions Django : clearsessions chaque nuit.',
    'django_admin_log':
        'Historique admin Django : 365 j.',
    'messaging_message':
        'Messages : données métier, conserver (archivage éventuel > 2 ans).',
    'orders_commande':
        'Commandes : données métier et comptables, conserver.',
    'orders_lignecommande':
        'Lignes de commande : données métier, conserver avec les commandes.',
    'orders_historiquecommande':
        'Historique de commande : conserver 2 ans, puis ne garder que la dernière ligne.',
    'livraison_course':
        'Courses : données métier, conserver.',
    'spatial_ref_sys':
        'Table système PostGIS : ne pas toucher.',
}
DEFAUT = 'À examiner (donnée métier probable : conserver tant que non qualifiée).'


def _taille(octets):
    for unite in ('o', 'Ko', 'Mo', 'Go'):
        if octets < 1024:
            return f'{octets:.0f} {unite}'
        octets /= 1024
    return f'{octets:.1f} To'


class Command(BaseCommand):
    help = 'Tables les plus lourdes (taille, lignes) + propositions de conservation. Lecture seule.'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=10)
        parser.add_argument('--markdown', action='store_true')

    def handle(self, *args, **options):
        with connection.cursor() as c:
            c.execute("""
                SELECT c.relname, pg_total_relation_size(c.oid) AS total,
                       pg_relation_size(c.oid) AS donnees
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r' AND n.nspname = 'public'
                ORDER BY total DESC LIMIT %s
            """, [options['top']])
            tables = c.fetchall()
            lignes = []
            for nom, total, donnees in tables:
                c.execute(f'SELECT count(*) FROM "{nom}"')
                lignes.append((nom, total, donnees, c.fetchone()[0]))

        if options['markdown']:
            self.stdout.write('| # | Table | Taille totale | Données | Lignes | Proposition |')
            self.stdout.write('|---|---|---|---|---|---|')
            for i, (nom, total, donnees, n) in enumerate(lignes, 1):
                nb = f'{n:,}'.replace(',', ' ')
                self.stdout.write(f'| {i} | {nom} | {_taille(total)} | {_taille(donnees)} | '
                                  f'{nb} | {PROPOSITIONS.get(nom, DEFAUT)} |')
            return
        for i, (nom, total, donnees, n) in enumerate(lignes, 1):
            self.stdout.write(f'{i:>2}. {nom:<45} {_taille(total):>10} (données {_taille(donnees)}) '
                              f'{n:>12,} lignes'.replace(',', ' '))
            self.stdout.write(f'    → {PROPOSITIONS.get(nom, DEFAUT)}')
