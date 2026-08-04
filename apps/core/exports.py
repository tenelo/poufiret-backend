"""Utilitaire d'export CSV commun à tout le projet.

Centralise le format retenu avec Tenelo :
  - séparateur point-virgule ';' (Excel FR ouvre proprement en colonnes) ;
  - BOM UTF-8 (\\ufeff) pour que les accents et les numéros de téléphone
    s'affichent correctement à l'ouverture dans Excel ;
  - nom de fichier horodaté.

Objectif : ne plus réécrire le bloc CSV dans chaque vue. Tout endpoint qui
expose des données admin peut renvoyer un export en 3 lignes. Un .xlsx natif
pourra être ajouté plus tard, ciblé, sans toucher aux appels existants.
"""
import csv
from django.http import HttpResponse
from django.utils import timezone


def reponse_csv(nom_fichier, entetes, lignes):
    """Construit une HttpResponse CSV téléchargeable.

    nom_fichier : base du nom, sans extension ni horodatage
                  (ex. 'stats_connexion'). Le résultat sera
                  'poufiret_stats_connexion_AAAAMMJJ_HHMM.csv'.
    entetes     : liste des titres de colonnes (ligne d'en-tête).
    lignes      : itérable de listes/tuples, une par ligne de données.
                  Les valeurs None sont rendues comme chaîne vide.
    """
    horodatage = timezone.localtime().strftime('%Y%m%d_%H%M')
    reponse = HttpResponse(content_type='text/csv; charset=utf-8')
    reponse['Content-Disposition'] = (
        f'attachment; filename="poufiret_{nom_fichier}_{horodatage}.csv"'
    )
    reponse.write('\ufeff')  # BOM pour Excel
    writer = csv.writer(reponse, delimiter=';')
    writer.writerow(entetes)
    for ligne in lignes:
        writer.writerow(['' if v is None else v for v in ligne])
    return reponse
