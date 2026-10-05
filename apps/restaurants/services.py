"""Services du module restaurants : ouverture/fermeture, résolution du menu
en vigueur, gestion du stock journalier, validations de commande.

Centralise toute la logique métier non triviale pour que les vues (public,
mon-restaurant, admin) et apps.orders s'y greffent sans la dupliquer.
"""
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.users.models import ProfilPartenaire

from .models import LigneMenu, MenuProgramme, ProfilRestaurant, StockJournalierLigneMenu

# Types de partenaires concernés par ce module. 'fastfood' sera ajouté à
# ProfilPartenaire.TypePartenaire et à cette liste quand ce vertical sera
# activé — aucune autre valeur n'existe aujourd'hui en base.
TYPES_RESTAURATION = [ProfilPartenaire.TypePartenaire.RESTAURATEUR]

LIBELLES_JOUR_ISO = {1: 'lundi', 2: 'mardi', 3: 'mercredi', 4: 'jeudi',
                     5: 'vendredi', 6: 'samedi', 7: 'dimanche'}


# ═══════════════════════════════════════════════════════════════════════
# OUVERTURE / FERMETURE (fuseau Africa/Abidjan — settings.TIME_ZONE)
# ═══════════════════════════════════════════════════════════════════════

def _plages_du_jour(partenaire, jour_iso):
    """Plages (debut, fin) ouvertes pour ce jour ISO (1=lundi), à partir de
    HoraireOuverture (jour_semaine 0=lundi — conversion ici). Une pause
    coupe la plage en deux (= « une ou plusieurs plages »)."""
    h = partenaire.horaires.filter(jour_semaine=jour_iso - 1, ouvert=True).first()
    if h is None or h.heure_ouverture is None or h.heure_fermeture is None:
        return []
    if h.pause_debut and h.pause_fin and h.pause_debut < h.pause_fin:
        return [(h.heure_ouverture, h.pause_debut), (h.pause_fin, h.heure_fermeture)]
    return [(h.heure_ouverture, h.heure_fermeture)]


def fiche_de(partenaire):
    """Fiche restaurant du partenaire, créée si absente (lecture comme
    écriture) — un restaurateur a toujours une fiche, même vide."""
    fiche, _cree = ProfilRestaurant.objects.get_or_create(partenaire=partenaire)
    return fiche


def statut(fiche, maintenant=None):
    """Bloc de statut commun à la liste, au détail et aux menus du jour."""
    prochaine = prochaine_ouverture(fiche, maintenant)
    return {
        'est_ouvert': est_ouvert(fiche, maintenant),
        'prochaine_ouverture': prochaine.isoformat() if prochaine else None,
        'message_statut': message_statut(fiche, maintenant),
    }


def fiches_de(partenaires):
    """{partenaire_id: fiche} pour une liste de partenaires, en 2 requêtes
    au plus : crée en bloc les fiches manquantes puis les relit."""
    ids = [p.id for p in partenaires]
    existantes = set(ProfilRestaurant.objects.filter(partenaire_id__in=ids)
                     .values_list('partenaire_id', flat=True))
    manquantes = [ProfilRestaurant(partenaire_id=i) for i in ids if i not in existantes]
    if manquantes:
        ProfilRestaurant.objects.bulk_create(manquantes, ignore_conflicts=True)
    return {f.partenaire_id: f for f in ProfilRestaurant.objects.filter(partenaire_id__in=ids)}


def _fermeture_exceptionnelle_active(fiche, maintenant):
    if not fiche.ferme_exceptionnellement:
        return False
    if fiche.ferme_jusqu_au is None:
        return True
    return timezone.localtime(maintenant).date() <= fiche.ferme_jusqu_au


def est_ouvert(fiche, maintenant=None):
    """Vrai si le restaurant est ouvert à l'instant `maintenant` (défaut :
    maintenant réel), heure locale Africa/Abidjan."""
    maintenant = maintenant or timezone.now()
    if _fermeture_exceptionnelle_active(fiche, maintenant):
        return False
    local = timezone.localtime(maintenant)
    for debut, fin in _plages_du_jour(fiche.partenaire, local.isoweekday()):
        if debut <= local.time() <= fin:
            return True
    return False


def prochaine_ouverture(fiche, maintenant=None):
    """Prochain datetime (aware, Africa/Abidjan) où le restaurant rouvre,
    ou None si aucun horaire n'est configuré ou si la fermeture
    exceptionnelle n'a pas de fin connue (jusqu_au absent)."""
    maintenant = maintenant or timezone.now()
    if fiche.ferme_exceptionnellement and fiche.ferme_jusqu_au is None:
        return None
    local = timezone.localtime(maintenant)
    depart = local.date()
    if _fermeture_exceptionnelle_active(fiche, maintenant):
        depart = fiche.ferme_jusqu_au + timedelta(days=1)
    for decalage in range(8):  # jusqu'à une semaine complète
        jour = depart + timedelta(days=decalage)
        for debut, _fin in _plages_du_jour(fiche.partenaire, jour.isoweekday()):
            if decalage == 0 and jour == local.date() and debut <= local.time():
                continue  # plage déjà entamée ou passée aujourd'hui
            naif = datetime.combine(jour, debut)
            return timezone.make_aware(naif) if timezone.is_naive(naif) else naif
    return None


def message_statut(fiche, maintenant=None):
    """« Ouvert · ferme à 22h », « Fermé · ouvre à 11h », « Fermé
    exceptionnellement : <motif> », « Horaires non renseignés »."""
    maintenant = maintenant or timezone.now()
    if _fermeture_exceptionnelle_active(fiche, maintenant):
        return f'Fermé exceptionnellement : {fiche.motif_fermeture}' if fiche.motif_fermeture \
            else 'Fermé exceptionnellement'
    if not fiche.partenaire.horaires.exists():
        return 'Horaires non renseignés'
    local = timezone.localtime(maintenant)
    if est_ouvert(fiche, maintenant):
        for debut, fin in _plages_du_jour(fiche.partenaire, local.isoweekday()):
            if debut <= local.time() <= fin:
                return f'Ouvert · ferme à {fin.strftime("%Hh%M").replace("h00", "h")}'
    ouverture = prochaine_ouverture(fiche, maintenant)
    if ouverture is None:
        return 'Fermé'
    ouverture_locale = timezone.localtime(ouverture)
    if ouverture_locale.date() == local.date():
        return f'Fermé · ouvre à {ouverture_locale.strftime("%Hh%M").replace("h00", "h")}'
    return (f'Fermé · ouvre {LIBELLES_JOUR_ISO[ouverture_locale.isoweekday()]} à '
           f'{ouverture_locale.strftime("%Hh%M").replace("h00", "h")}')


# ═══════════════════════════════════════════════════════════════════════
# RÉSOLUTION DU MENU EN VIGUEUR
# ═══════════════════════════════════════════════════════════════════════

def menu_en_vigueur(restaurant, pour_date, service):
    """Menu applicable pour ce restaurant, cette date et ce service :
    1) menu daté publié de cette date+service ;
    2) sinon modèle hebdomadaire publié de ce jour de semaine (ISO)+service ;
    3) sinon le dernier menu publié de ce service (toutes natures/dates),
       pour que le même menu reste en place sans changement explicite.
    """
    base = MenuProgramme.objects.filter(
        restaurant=restaurant, service=service, publie=True)
    menu = base.filter(nature=MenuProgramme.Nature.DATE, date=pour_date).first()
    if menu:
        return menu
    menu = base.filter(
        nature=MenuProgramme.Nature.HEBDOMADAIRE,
        jour_semaine=pour_date.isoweekday()).first()
    if menu:
        return menu
    return base.order_by('-modifie_le').first()


def menus_du_jour(restaurant, pour_date=None):
    """{'midi': menu|None, 'soir': menu|None, 'journee': menu|None}."""
    pour_date = pour_date or timezone.localdate()
    return {
        service: menu_en_vigueur(restaurant, pour_date, service)
        for service, _l in MenuProgramme.Service.choices
    }


def menus_en_vigueur_maintenant(restaurant, maintenant=None):
    """Parmi les menus du jour, ceux dont la fenêtre [heure_debut, heure_fin]
    contient l'instant donné (défaut : maintenant). Peut être vide (ex.
    entre le service de midi et celui du soir)."""
    maintenant = maintenant or timezone.now()
    local = timezone.localtime(maintenant)
    menus = menus_du_jour(restaurant, local.date())
    return {s: m for s, m in menus.items()
            if m and m.heure_debut <= local.time() <= m.heure_fin}


def menu_commandable(menu, maintenant=None):
    """Vrai si l'heure limite de commande (si posée) n'est pas dépassée."""
    if menu is None:
        return False
    maintenant = maintenant or timezone.now()
    local = timezone.localtime(maintenant)
    if menu.heure_limite_commande and local.time() > menu.heure_limite_commande:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# STOCK JOURNALIER (par ligne de menu, par date)
# ═══════════════════════════════════════════════════════════════════════

def _date_du_menu(ligne_menu, pour_date=None):
    """Date de référence du stock : la date propre du menu s'il est daté,
    sinon la date demandée (défaut aujourd'hui) pour un menu hebdomadaire."""
    if ligne_menu.menu.nature == MenuProgramme.Nature.DATE:
        return ligne_menu.menu.date
    return pour_date or timezone.localdate()


def stock_restant(ligne_menu, pour_date=None):
    """Stock restant pour la date de référence. None = illimité (pas de
    stock_initial posé). Ne crée pas la ligne StockJournalierLigneMenu si
    elle n'existe pas encore (lecture pure) : renvoie stock_initial."""
    if ligne_menu.stock_initial is None:
        return None
    jour = _date_du_menu(ligne_menu, pour_date)
    ligne = StockJournalierLigneMenu.objects.filter(
        ligne_menu=ligne_menu, date=jour).first()
    return ligne.restant if ligne else ligne_menu.stock_initial


def plat_epuise(ligne_menu, pour_date=None):
    restant = stock_restant(ligne_menu, pour_date)
    return restant is not None and restant <= 0


class StockInsuffisantError(Exception):
    pass


@transaction.atomic
def decrementer_stock(ligne_menu, quantite, pour_date=None):
    """Décrémente le stock du jour, verrouillé (select_for_update) pour
    éviter une survente en cas de commandes simultanées. Ne fait rien si
    la ligne n'a pas de quota (stock_initial=None, illimité)."""
    if ligne_menu.stock_initial is None:
        return
    jour = _date_du_menu(ligne_menu, pour_date)
    ligne, _cree = StockJournalierLigneMenu.objects.select_for_update().get_or_create(
        ligne_menu=ligne_menu, date=jour,
        defaults={'restant': ligne_menu.stock_initial})
    if ligne.restant < quantite:
        raise StockInsuffisantError(
            f'Stock insuffisant pour « {ligne_menu.plat.nom} » '
            f'({ligne.restant} restant(s)).')
    ligne.restant -= quantite
    ligne.save(update_fields=['restant'])


@transaction.atomic
def restaurer_stock(ligne_menu, quantite, pour_date=None):
    """Restaure le stock du jour (annulation/refus d'une commande)."""
    if ligne_menu is None or ligne_menu.stock_initial is None:
        return
    jour = _date_du_menu(ligne_menu, pour_date)
    ligne, cree = StockJournalierLigneMenu.objects.select_for_update().get_or_create(
        ligne_menu=ligne_menu, date=jour,
        defaults={'restant': ligne_menu.stock_initial})
    if not cree:
        ligne.restant = min(ligne.restant + quantite, ligne_menu.stock_initial)
        ligne.save(update_fields=['restant'])


# ═══════════════════════════════════════════════════════════════════════
# DUPLICATION DE MENU
# ═══════════════════════════════════════════════════════════════════════

def dupliquer_menu(menu, *, vers_date=None, vers_jour_semaine=None,
                   acteur_role='', acteur_nom=''):
    """Duplique un menu (et ses lignes) vers une nouvelle date (nature
    'date') ou un nouveau jour de semaine (nature 'hebdomadaire'). Le
    nouveau menu est créé NON publié (publie=False) — à publier
    explicitement. Un seul des deux paramètres doit être fourni."""
    if bool(vers_date) == bool(vers_jour_semaine):
        raise ValueError('Fournir exactement un de vers_date / vers_jour_semaine.')
    nouveau = MenuProgramme.objects.create(
        restaurant=menu.restaurant,
        nature=MenuProgramme.Nature.DATE if vers_date else MenuProgramme.Nature.HEBDOMADAIRE,
        date=vers_date, jour_semaine=vers_jour_semaine,
        service=menu.service, heure_debut=menu.heure_debut, heure_fin=menu.heure_fin,
        titre=menu.titre, publie=False,
        heure_limite_commande=menu.heure_limite_commande,
        modifie_par_role=acteur_role, modifie_par_nom=acteur_nom,
    )
    for ligne in menu.lignes.all():
        LigneMenu.objects.create(
            menu=nouveau, plat=ligne.plat, prix_menu=ligne.prix_menu,
            stock_initial=ligne.stock_initial, ordre=ligne.ordre,
            modifie_par_role=acteur_role, modifie_par_nom=acteur_nom,
        )
    return nouveau


def copier_semaine(restaurant, *, acteur_role='', acteur_nom=''):
    """Pour chaque menu hebdomadaire existant, s'assure qu'il y a bien un
    menu pour chacun des 7 jours en copiant le PREMIER menu hebdomadaire
    trouvé par service vers les jours manquants. Utile pour démarrer une
    semaine type à partir d'un seul jour déjà configuré. Retourne la liste
    des menus créés."""
    crees = []
    for service, _l in MenuProgramme.Service.choices:
        existants = MenuProgramme.objects.filter(
            restaurant=restaurant, nature=MenuProgramme.Nature.HEBDOMADAIRE,
            service=service)
        modele = existants.first()
        if modele is None:
            continue
        jours_existants = set(existants.values_list('jour_semaine', flat=True))
        for jour in range(1, 8):
            if jour in jours_existants:
                continue
            crees.append(dupliquer_menu(
                modele, vers_jour_semaine=jour,
                acteur_role=acteur_role, acteur_nom=acteur_nom))
    return crees
