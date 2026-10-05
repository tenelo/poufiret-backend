"""Modèles de l'app restaurants (Phase R1).

Extension additive de ProfilPartenaire (fiche restaurant) + menus
programmés. Réutilise apps.users.HoraireOuverture (générique, déjà lié à
ProfilPartenaire) pour les horaires hebdomadaires — aucun nouveau modèle
d'horaire créé. Réutilise apps.catalog.Article pour les plats (y compris
GroupeOption/OptionGroupe pour les options, et Variante pour les tailles/
formats). Rien ici n'est dupliqué depuis ces modules.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Article
from apps.users.models import ProfilPartenaire


class ModeService(models.TextChoices):
    """Services proposés par le restaurant. Mêmes valeurs que
    Commande.ModeLivraison (apps.orders.models) — pas de duplication de
    vocabulaire, juste une liste (JSONField) ici plutôt qu'un choix unique."""
    SUR_PLACE = 'sur_place', _('Sur place')
    EMPORTER = 'emporter', _('À emporter')
    LIVRAISON = 'livraison', _('Livraison')


class ActeurRole(models.TextChoices):
    """Qui a fait la dernière modification — restaurateur ou admin agissant
    à sa place. Réutilisé par ProfilRestaurant, Article (via le plat) n'a
    pas ce champ : seuls les objets propres à ce module le portent."""
    RESTAURATEUR = 'restaurateur', _('Restaurateur')
    ADMIN = 'admin', _('Admin')


class ChampsTracabiliteMixin(models.Model):
    """modifie_par_role / modifie_par_nom / modifie_le — posés par les vues
    (pas par un signal) à chaque écriture, pour afficher « Modifié par
    l'administration le … » côté restaurateur."""
    modifie_par_role = models.CharField(
        _('modifié par (rôle)'), max_length=12, choices=ActeurRole.choices,
        blank=True,
    )
    modifie_par_nom = models.CharField(_('modifié par (nom)'), max_length=150, blank=True)
    modifie_le = models.DateTimeField(_('modifié le'), auto_now=True)

    class Meta:
        abstract = True


class ProfilRestaurant(ChampsTracabiliteMixin, models.Model):
    """Fiche restaurant : extension 1-1 de ProfilPartenaire. Ne concerne
    que les partenaires dont le type est dans TYPES_RESTAURATION (voir
    services.py) — non imposé au niveau base, décidé à la création."""
    partenaire = models.OneToOneField(
        ProfilPartenaire, on_delete=models.CASCADE,
        related_name='profil_restaurant', verbose_name=_('partenaire'),
    )

    ferme_exceptionnellement = models.BooleanField(
        _('fermé exceptionnellement'), default=False)
    motif_fermeture = models.CharField(_('motif de fermeture'), max_length=255, blank=True)
    ferme_jusqu_au = models.DateField(_('fermé jusqu\'au'), blank=True, null=True)

    services = models.JSONField(
        _('services proposés'), default=list, blank=True,
        help_text=_('Liste parmi : sur_place, emporter, livraison.'),
    )
    delai_preparation_min = models.PositiveIntegerField(
        _('délai de préparation (min)'), default=20)

    # Pas de champ whatsapp ici : ProfilPartenaire.whatsapp existe déjà
    # (apps.users.models) — réutilisé tel quel, non dupliqué.
    adresse_reperes = models.TextField(
        _('adresse détaillée / repères'), blank=True,
        help_text=_('Ex. "en face de la pharmacie, 2e rue à droite".'))

    facebook = models.URLField(_('Facebook'), blank=True)
    instagram = models.URLField(_('Instagram'), blank=True)
    tiktok = models.URLField(_('TikTok'), blank=True)

    specialites = models.JSONField(
        _('spécialités'), default=list, blank=True,
        help_text=_('Liste courte, ex. ["Garba", "Grillades", "Pizza"].'))

    cree_le = models.DateTimeField(_('créé le'), auto_now_add=True)

    class Meta:
        verbose_name = _('profil restaurant')
        verbose_name_plural = _('profils restaurant')

    def __str__(self):
        return f'Fiche restaurant — {self.partenaire.nom_commerce}'


class TelephoneRestaurant(models.Model):
    """Téléphone supplémentaire d'un restaurant (libellé + numéro) — en
    plus de User.telephone (compte) et ProfilPartenaire.telephone_pro
    (déjà existants, inchangés), pour les cas « cuisine », « livraison »…"""
    restaurant = models.ForeignKey(
        ProfilRestaurant, on_delete=models.CASCADE,
        related_name='telephones', verbose_name=_('restaurant'),
    )
    libelle = models.CharField(_('libellé'), max_length=50, blank=True)
    numero = models.CharField(_('numéro'), max_length=20)
    ordre = models.IntegerField(_('ordre'), default=0)

    class Meta:
        verbose_name = _('téléphone de restaurant')
        verbose_name_plural = _('téléphones de restaurant')
        ordering = ['restaurant', 'ordre']

    def __str__(self):
        return f'{self.restaurant} — {self.libelle or self.numero}'


class MenuProgramme(ChampsTracabiliteMixin, models.Model):
    """Menu (ex. menu du jour) rattaché à un restaurant."""

    class Nature(models.TextChoices):
        HEBDOMADAIRE = 'hebdomadaire', _('Hebdomadaire (jour de semaine)')
        DATE = 'date', _('Daté (un jour précis)')

    class Service(models.TextChoices):
        MIDI = 'midi', _('Midi')
        SOIR = 'soir', _('Soir')
        JOURNEE = 'journee', _('Journée')

    restaurant = models.ForeignKey(
        ProfilRestaurant, on_delete=models.CASCADE,
        related_name='menus', verbose_name=_('restaurant'),
    )
    nature = models.CharField(_('nature'), max_length=15, choices=Nature.choices)
    jour_semaine = models.PositiveSmallIntegerField(
        _('jour de la semaine'), blank=True, null=True,
        help_text=_('1 à 7, lundi = 1. Requis si nature = hebdomadaire.'))
    date = models.DateField(_('date'), blank=True, null=True,
                            help_text=_('Requis si nature = date.'))
    service = models.CharField(_('service'), max_length=10, choices=Service.choices)
    heure_debut = models.TimeField(_('heure de début'))
    heure_fin = models.TimeField(_('heure de fin'))
    titre = models.CharField(_('titre'), max_length=150, blank=True)
    publie = models.BooleanField(_('publié'), default=False)
    heure_limite_commande = models.TimeField(
        _('heure limite de commande'), blank=True, null=True)

    cree_le = models.DateTimeField(_('créé le'), auto_now_add=True)

    class Meta:
        verbose_name = _('menu programmé')
        verbose_name_plural = _('menus programmés')
        ordering = ['-modifie_le']
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(nature='hebdomadaire', jour_semaine__isnull=False, date__isnull=True)
                    | models.Q(nature='date', date__isnull=False, jour_semaine__isnull=True)
                ),
                name='menu_nature_coherente',
            ),
        ]
        indexes = [
            models.Index(fields=['restaurant', 'nature', 'service', 'publie']),
            models.Index(fields=['restaurant', 'date', 'service']),
            models.Index(fields=['restaurant', 'jour_semaine', 'service']),
        ]

    def __str__(self):
        cible = f'le {self.date}' if self.nature == 'date' else f'jour {self.jour_semaine}'
        return f'{self.restaurant.partenaire.nom_commerce} — {self.get_service_display()} ({cible})'


class LigneMenu(ChampsTracabiliteMixin, models.Model):
    """Un plat dans un menu, avec son prix propre au menu (optionnel) et son
    quota journalier (optionnel, nul = illimité). Le compteur RÉEL du jour
    vit dans StockJournalierLigneMenu — stock_initial n'est jamais écrasé
    (voir apps.restaurants.services.stock_restant_de)."""
    menu = models.ForeignKey(
        MenuProgramme, on_delete=models.CASCADE,
        related_name='lignes', verbose_name=_('menu'),
    )
    plat = models.ForeignKey(
        Article, on_delete=models.PROTECT,
        related_name='lignes_menu', verbose_name=_('plat'),
    )
    prix_menu = models.DecimalField(
        _('prix dans le menu (FCFA)'), max_digits=12, decimal_places=0,
        blank=True, null=True, help_text=_('Vide = prix de base du plat.'))
    stock_initial = models.PositiveIntegerField(
        _('stock initial (par jour)'), blank=True, null=True,
        help_text=_('Vide = illimité. Repart de cette valeur chaque jour.'))
    ordre = models.IntegerField(_('ordre'), default=0)

    class Meta:
        verbose_name = _('ligne de menu')
        verbose_name_plural = _('lignes de menu')
        ordering = ['menu', 'ordre']

    def __str__(self):
        return f'{self.menu} — {self.plat.nom}'

    @property
    def prix_effectif(self):
        return self.prix_menu if self.prix_menu is not None else self.plat.prix


class StockJournalierLigneMenu(models.Model):
    """Compteur de stock RÉEL d'une ligne de menu pour UNE date donnée —
    jamais le modèle LigneMenu.stock_initial lui-même (qui reste le gabarit
    rejoué chaque jour pour un menu hebdomadaire). Une ligne de menu datée
    n'a besoin que d'une seule de ces lignes (sa propre date)."""
    ligne_menu = models.ForeignKey(
        LigneMenu, on_delete=models.CASCADE,
        related_name='stocks_jour', verbose_name=_('ligne de menu'),
    )
    date = models.DateField(_('date'))
    restant = models.PositiveIntegerField(_('stock restant'))

    class Meta:
        verbose_name = _('stock journalier de ligne de menu')
        verbose_name_plural = _('stocks journaliers de ligne de menu')
        constraints = [
            models.UniqueConstraint(fields=['ligne_menu', 'date'],
                                    name='unique_stock_jour_par_ligne'),
        ]

    def __str__(self):
        return f'{self.ligne_menu} — {self.date} : {self.restant}'
