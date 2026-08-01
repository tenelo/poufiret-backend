"""
Modèles de l'app orders.

Module 4 du modèle Poufiret. Gère le panier et les commandes pour les
catégories transactionnelles (restaurants, fast-food, librairies).

Cycle de vie d'une commande :
    Panier ──validation──▶ Commande (statut: nouvelle)
                                ↓
                          ┌─────────────┬──────────────┐
                          ▼             ▼              ▼
                       acceptee     refusee        annulee
                          │                            ▲
                    en_preparation                     │
                          │                            │
                        prete ──────────expiree────────┘
                          │
                     en_livraison
                          │
                        livree
"""
from django.db import models # type: ignore
from django.utils.translation import gettext_lazy as _ # type: ignore

from apps.catalog.models import Article
from apps.users.models import AdresseClient, ProfilPartenaire, User


# ═══════════════════════════════════════════════════════════════════════
# PANIER (brouillon avant validation)
# ═══════════════════════════════════════════════════════════════════════

class Panier(models.Model):
    """
    Panier d'un client, pur par (commerçant, catégorie).
    Un client peut avoir plusieurs paniers simultanés : un par couple
    (commerçant, catégorie). Ex. : poisson chez Tenelo et chaussures chez
    Tenelo sont deux paniers distincts. Permet un affichage et une commande
    regroupés par catégorie côté client.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='paniers',
        verbose_name=_('utilisateur'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire,
        on_delete=models.CASCADE,
        related_name='paniers',
        verbose_name=_('commerçant'),
    )
    categorie = models.ForeignKey(
            'catalog.Categorie',
            on_delete=models.CASCADE,
            related_name='paniers',
            verbose_name=_('catégorie'),
        )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('panier')
        verbose_name_plural = _('paniers')
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'partenaire', 'categorie'],
                name='unique_panier_par_triplet',
            ),
        ]

    def __str__(self):
        return f"Panier {self.user.telephone} → {self.partenaire.nom_commerce}"


class LignePanier(models.Model):
    """
    Une ligne dans un panier : article + quantité + variantes/suppléments choisis.
    Le prix unitaire est figé au moment de l'ajout pour éviter les surprises
    si le commerçant change ses prix entre l'ajout et la validation.
    """
    panier = models.ForeignKey(
        Panier,
        on_delete=models.CASCADE,
        related_name='lignes',
        verbose_name=_('panier'),
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='lignes_panier',
        verbose_name=_('article'),
    )

    # Choix du client
    variante_id = models.IntegerField(
        _('variante choisie'),
        blank=True, null=True,
        help_text=_('ID de la Variante sélectionnée (Petit/Moyen/Grand).'),
    )
    supplements = models.JSONField(
        _('suppléments choisis'),
        default=list, blank=True,
        help_text=_('Liste d\'objets [{id, nom, prix}…] figés au moment de l\'ajout.'),
    )

    quantite = models.PositiveIntegerField(_('quantité'), default=1)
    prix_unitaire = models.DecimalField(
        _('prix unitaire (FCFA)'),
        max_digits=12, decimal_places=0,
        help_text=_('Snapshot au moment de l\'ajout au panier.'),
    )
    note_speciale = models.TextField(
        _('note spéciale'),
        blank=True,
        help_text=_('Ex: "Sans oignons s\'il vous plaît".'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('ligne de panier')
        verbose_name_plural = _('lignes de panier')
        ordering = ['panier', 'created_at']

    def __str__(self):
        return f"{self.quantite} × {self.article.nom}"


# ═══════════════════════════════════════════════════════════════════════
# COMMANDE (panier validé)
# ═══════════════════════════════════════════════════════════════════════

class Commande(models.Model):
    """
    Commande validée par un client auprès d'un commerçant.
    Workflow de statut géré explicitement.
    """

    class Statut(models.TextChoices):
        NOUVELLE = 'nouvelle', _('Nouvelle')
        ACCEPTEE = 'acceptee', _('Acceptée')
        REFUSEE = 'refusee', _('Refusée')
        EN_PREPARATION = 'en_preparation', _('En préparation')
        PRETE = 'prete', _('Prête')
        EN_LIVRAISON = 'en_livraison', _('En livraison')
        LIVREE = 'livree', _('Livrée')
        ANNULEE = 'annulee', _('Annulée')
        EXPIREE = 'expiree', _('Expirée (non récupérée)')

    class ModeLivraison(models.TextChoices):
        EMPORTER = 'emporter', _('À emporter')
        SUR_PLACE = 'sur_place', _('Sur place')
        LIVRAISON = 'livraison', _('Livraison')

    class ModePaiement(models.TextChoices):
        CASH = 'cash', _('Espèces')
        MOBILE_MONEY = 'mobile_money', _('Mobile Money')

    # ── Identité ─────────────────────────────────────────────────────
    numero = models.CharField(
        _('numéro de commande'),
        max_length=30, unique=True,
        help_text=_('Ex: PFR-2026-00125 (généré automatiquement).'),
    )
    user = models.ForeignKey(
        User, on_delete=models.PROTECT,
        related_name='commandes', verbose_name=_('client'),
    )
    partenaire = models.ForeignKey(
        ProfilPartenaire, on_delete=models.PROTECT,
        related_name='commandes', verbose_name=_('commerçant'),
    )

    # ── Mode de livraison et adresse ─────────────────────────────────
    mode_livraison = models.CharField(
        _('mode de livraison'),
        max_length=20, choices=ModeLivraison.choices,
        default=ModeLivraison.EMPORTER,
    )
    adresse = models.ForeignKey(
        AdresseClient,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='commandes',
        verbose_name=_('adresse de livraison'),
    )
    adresse_snapshot = models.CharField(
        _('adresse (snapshot)'),
        max_length=500, blank=True,
        help_text=_('Copie figée de l\'adresse au moment de la commande.'),
    )
    heure_souhaitee = models.DateTimeField(
        _('heure souhaitée'),
        blank=True, null=True,
    )

    # ── Statut ───────────────────────────────────────────────────────
    statut = models.CharField(
        _('statut'),
        max_length=20, choices=Statut.choices,
        default=Statut.NOUVELLE,
    )
    raison_refus = models.TextField(_('raison du refus'), blank=True)
    annulee_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='commandes_annulees',
        verbose_name=_('annulée par'),
    )

    # ── Montants ─────────────────────────────────────────────────────
    sous_total = models.DecimalField(
        _('sous-total (FCFA)'),
        max_digits=12, decimal_places=0, default=0,
    )
    frais_livraison = models.DecimalField(
        _('frais de livraison (FCFA)'),
        max_digits=10, decimal_places=0, default=0,
    )
    total = models.DecimalField(
        _('total (FCFA)'),
        max_digits=12, decimal_places=0, default=0,
    )
    mode_paiement = models.CharField(
        _('mode de paiement'),
        max_length=30, choices=ModePaiement.choices,
        default=ModePaiement.CASH,
        help_text=_('À titre informatif (pas de paiement intégré en MVP).'),
    )

    # ── Notes ────────────────────────────────────────────────────────
    notes_client = models.TextField(_('notes du client'), blank=True)
    notes_partenaire = models.TextField(_('notes du commerçant'), blank=True)

    # ── Dates clés du workflow ───────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    acceptee_le = models.DateTimeField(_('acceptée le'), blank=True, null=True)
    prete_le = models.DateTimeField(_('prête le'), blank=True, null=True)
    livree_le = models.DateTimeField(_('livrée le'), blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('commande')
        verbose_name_plural = _('commandes')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['partenaire', 'statut', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f"{self.numero} — {self.partenaire.nom_commerce}"


class LigneCommande(models.Model):
    """
    Une ligne de commande figée (snapshot).
    Contrairement à LignePanier, les noms de l'article et de la variante
    sont copiés ici pour qu'ils restent intacts même si le commerçant
    modifie ou supprime l'article plus tard.
    """
    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name='lignes',
        verbose_name=_('commande'),
    )
    article = models.ForeignKey(
        Article,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='lignes_commande',
        verbose_name=_('article'),
        help_text=_('Peut être null si l\'article a été supprimé après commande.'),
    )

    # Snapshots figés
    nom_article = models.CharField(_('nom de l\'article'), max_length=200)
    variante_nom = models.CharField(_('nom de la variante'), max_length=50, blank=True)
    supplements = models.JSONField(
        _('suppléments'),
        default=list, blank=True,
        help_text=_('Snapshot des suppléments choisis [{nom, prix}…].'),
    )

    quantite = models.PositiveIntegerField(_('quantité'))
    prix_unitaire = models.DecimalField(
        _('prix unitaire (FCFA)'),
        max_digits=12, decimal_places=0,
    )
    prix_ligne = models.DecimalField(
        _('prix de la ligne (FCFA)'),
        max_digits=12, decimal_places=0,
        help_text=_('quantité × prix_unitaire (+ éventuels suppléments).'),
    )
    note_speciale = models.TextField(_('note spéciale'), blank=True)

    class Meta:
        verbose_name = _('ligne de commande')
        verbose_name_plural = _('lignes de commande')
        ordering = ['commande', 'id']

    def __str__(self):
        return f"{self.quantite} × {self.nom_article}"

    