"""Tests : apps.restaurants.services (ouverture/fermeture, résolution de
menu dated > hebdomadaire > dernier publié, stock journalier, duplication).

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_restaurants_services.py
"""
from datetime import date, time, timedelta
from django.db import transaction
from django.utils import timezone
from apps.users.models import ProfilPartenaire, HoraireOuverture, User
from apps.restaurants.models import ProfilRestaurant, MenuProgramme, LigneMenu
from apps.catalog.models import Categorie, Article
from apps.restaurants import services as rs

class Rollback(Exception): pass
NB=0
def ok(l, c, d=''):
    global NB
    print(('OK   ' if c else 'FAIL '), l, '' if c else d)
    assert c, f'{l} {d}'
    NB += 1

try:
    with transaction.atomic():
        pa = ProfilPartenaire.objects.filter(type_partenaire='restaurateur').first()
        ProfilRestaurant.objects.filter(partenaire=pa).delete()
        fiche = ProfilRestaurant.objects.create(partenaire=pa)
        HoraireOuverture.objects.filter(partenaire=pa).delete()
        # Lundi(0) a Dimanche(6) : ouvert 11h-22h avec pause 15h-18h, sauf dimanche ferme
        for j in range(6):
            HoraireOuverture.objects.create(partenaire=pa, jour_semaine=j, ouvert=True,
                heure_ouverture=time(11,0), heure_fermeture=time(22,0),
                pause_debut=time(15,0), pause_fin=time(18,0))
        HoraireOuverture.objects.create(partenaire=pa, jour_semaine=6, ouvert=False)

        print('=== 1. OUVERTURE/FERMETURE ===')
        lundi_12h = timezone.make_aware(timezone.datetime(2026,10,5,12,0))  # lundi
        ok('ouvert lundi 12h', rs.est_ouvert(fiche, lundi_12h) is True)
        lundi_16h = timezone.make_aware(timezone.datetime(2026,10,5,16,0))
        ok('ferme lundi 16h (pause)', rs.est_ouvert(fiche, lundi_16h) is False)
        msg = rs.message_statut(fiche, lundi_16h)
        ok(f'message_statut pause = "{msg}"', 'Fermé' in msg and 'ouvre à 18h' in msg, msg)
        lundi_23h = timezone.make_aware(timezone.datetime(2026,10,5,23,0))
        msg2 = rs.message_statut(fiche, lundi_23h)
        ok(f'message_statut nuit = "{msg2}"', 'mardi' in msg2 or 'ouvre' in msg2, msg2)
        dimanche_12h = timezone.make_aware(timezone.datetime(2026,10,11,12,0))  # dimanche
        ok('ferme dimanche (jour ferme)', rs.est_ouvert(fiche, dimanche_12h) is False)

        fiche.ferme_exceptionnellement = True
        fiche.motif_fermeture = 'Congés annuels'
        fiche.ferme_jusqu_au = None
        fiche.save()
        ok('ferme exceptionnellement (sans fin) -> False', rs.est_ouvert(fiche, lundi_12h) is False)
        ok('message = motif', rs.message_statut(fiche, lundi_12h) == 'Fermé exceptionnellement : Congés annuels')
        ok('prochaine_ouverture = None sans fin connue', rs.prochaine_ouverture(fiche, lundi_12h) is None)
        fiche.ferme_jusqu_au = date(2026,10,5)
        fiche.save()
        ok('fermeture exceptionnelle avec fin passee -> rouvre normalement le 6',
           rs.est_ouvert(fiche, timezone.make_aware(timezone.datetime(2026,10,6,12,0))) is True)
        fiche.ferme_exceptionnellement = False
        fiche.save()

        print('=== 2. RESOLUTION MENU ===')
        cat = Categorie.objects.filter(est_archivee=False).first()
        def plat(nom):
            from django.utils.text import slugify; return Article.objects.create(partenaire=pa, categorie=cat, nom=nom, slug=slugify(nom), type='plat', prix=2000)
        riz_sauce = plat('Riz sauce graine')
        attieke_poisson = plat('Attiéké poisson')
        menu_hebdo = MenuProgramme.objects.create(
            restaurant=fiche, nature='hebdomadaire', jour_semaine=1, service='midi',
            heure_debut=time(11,0), heure_fin=time(15,0), publie=True, titre='Menu lundi')
        LigneMenu.objects.create(menu=menu_hebdo, plat=riz_sauce, prix_menu=2000, ordre=1)
        resolu = rs.menu_en_vigueur(fiche, date(2026,10,5), 'midi')  # lundi
        ok('hebdomadaire resolu pour lundi', resolu.id == menu_hebdo.id)
        resolu2 = rs.menu_en_vigueur(fiche, date(2026,10,6), 'midi')  # mardi, rien de prevu
        ok('sans menu mardi -> dernier publie du service = le lundi (sans changement)',
           resolu2.id == menu_hebdo.id)

        menu_date = MenuProgramme.objects.create(
            restaurant=fiche, nature='date', date=date(2026,10,6), service='midi',
            heure_debut=time(11,0), heure_fin=time(15,0), publie=True, titre='Menu special mardi')
        LigneMenu.objects.create(menu=menu_date, plat=attieke_poisson, prix_menu=2500, ordre=1)
        resolu3 = rs.menu_en_vigueur(fiche, date(2026,10,6), 'midi')
        ok('date PUBLIEE prioritaire sur hebdomadaire', resolu3.id == menu_date.id)

        menu_non_publie = MenuProgramme.objects.create(
            restaurant=fiche, nature='date', date=date(2026,10,7), service='midi',
            heure_debut=time(11,0), heure_fin=time(15,0), publie=False)
        resolu4 = rs.menu_en_vigueur(fiche, date(2026,10,7), 'midi')
        ok('menu non publie ignore -> retombe sur hebdomadaire du jour (mercredi, aucun) -> dernier publie',
           resolu4.id in (menu_hebdo.id, menu_date.id), resolu4.id)

        print('=== 3. STOCK JOURNALIER ===')
        ligne_stock = LigneMenu.objects.create(menu=menu_hebdo, plat=riz_sauce, stock_initial=3, ordre=2)
        ok('stock_restant initial = stock_initial (pas encore cree)', rs.stock_restant(ligne_stock, date(2026,10,5)) == 3)
        rs.decrementer_stock(ligne_stock, 2, date(2026,10,5))
        ok('apres decrement de 2 -> restant 1', rs.stock_restant(ligne_stock, date(2026,10,5)) == 1)
        try:
            rs.decrementer_stock(ligne_stock, 5, date(2026,10,5))
            ok('decrement > stock -> leve StockInsuffisantError', False)
        except rs.StockInsuffisantError:
            ok('decrement > stock -> leve StockInsuffisantError', True)
        rs.restaurer_stock(ligne_stock, 1, date(2026,10,5))
        ok('restauration -> restant 2', rs.stock_restant(ligne_stock, date(2026,10,5)) == 2)
        ok('jour suivant (hebdomadaire) repart de stock_initial (3), sans toucher le jour precedent',
           rs.stock_restant(ligne_stock, date(2026,10,12)) == 3
           and rs.stock_restant(ligne_stock, date(2026,10,5)) == 2)
        rs.decrementer_stock(ligne_stock, 2, date(2026,10,5))
        ok('epuise a 0 -> plat_epuise True', rs.plat_epuise(ligne_stock, date(2026,10,5)) is True)

        print('=== 4. DUPLICATION ===')
        dup = rs.dupliquer_menu(menu_hebdo, vers_jour_semaine=2, acteur_role='restaurateur', acteur_nom='Test')
        ok('duplique vers mardi, non publie par defaut', dup.jour_semaine == 2 and dup.publie is False)
        ok('lignes dupliquees', dup.lignes.count() == menu_hebdo.lignes.count())

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback()
except Rollback:
    print('Rollback effectue.')
