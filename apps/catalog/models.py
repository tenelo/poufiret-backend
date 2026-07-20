"""
Modèles de l'app catalog.

Module 2 du modèle Poufiret. Couvre catégories, articles, photos, panoramas,
sections de menu, variantes, suppléments et tracking de vues.
"""
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.users.models import ProfilPartenaire, User


# ═══════════════════════════════════════════════════════════════════════
# CATÉGORIES
# ═══════════════════════════════════════════════════════════════════════

class Categorie(models.Model):
    """
    Catégories hiérarchiques de l'application.

    Une catégorie peut avoir un parent (Beauté & Bien-être → Coiffure Homme).
    Le mode_transaction définit comment les commerçants de cette catégorie
    vendent (vitrine + chat, panier, demande d'intervention, etc.).
    """

    class ModeTransaction(models.TextChoices):
        VITRINE_CHAT = 'vitrine_chat', _('Vitrine + Chat')
        PANIER_COMMANDE = 'panier_commande', _('Panier + Commande')
        CATALOGUE_DEMANDE = 'catalogue_demande_intervention', _('Catalogue + Demande d\'intervention')
        DEMANDE_INTERVENTION = 'demande_intervention', _('Demande d\'intervention')

    nom = models.CharField(_('nom'), max_length=100)
    slug = models.SlugField(_('slug'), max_length=120, unique=True)
    description = models.TextField(_('description'), blank=True)
    icone = models.CharField(
        _('icône'),
        max_length=50,
        blank=True,
        help_text=_('Emoji ou nom d\'icône (ex: "💇", "pharmacy").'),
    )
    image_couverture = models.ImageField(
        _('image d\'affiche du marché virtuel'),
        upload_to='categories/',
        blank=True, null=True,
    )

    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        blank=True, null=True,
        related_name='enfants',
        verbose_name=_('catégorie parente'),
        help_text=_('Vide si racine, sinon la catégorie qui l\'englobe.'),
    )

    types_articles = models.JSONField(
        _('types d\'articles autorisés'),
        default=list, blank=True,
        help_text=_('Liste des types proposés au partenaire pour cette catégorie, '
                    'ex: ["plat", "produit"]. Vide = tous les types.'),
    )
    mode_transaction = models.CharField(
        _('mode de transaction'),
        max_length=40,
        choices=ModeTransaction.choices,
        default=ModeTransaction.VITRINE_CHAT,
    )

    module_flutter = models.CharField(
        _('module Flutter'),
        max_length=50,
        blank=True,
        help_text=_('Nom du module Flutter associé (ex: "restaurants", "beaute").'),
    )

    ordre = models.IntegerField(_('ordre d\'affichage'), default=0)
    est_active = models.BooleanField(_('catégorie active'), default=True)
    est_archivee = models.BooleanField(
        _('catégorie archivée'), default=False,
        help_text=_('Archivée = totalement invisible dans l\'application. '
                    'Désactivée (case active décochée) = grisée "Bientôt disponible".'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('catégorie')
        verbose_name_plural = _('catégories')
        ordering = ['ordre', 'nom']

    def __str__(self):
        if self.parent:
            return f"{self.parent.nom} › {self.nom}"
        return self.nom


class PartenaireCategorie(models.Model):
    """
    Lien plusieurs-à-plusieurs entre commerçants et catégories.
    Un commerçant peut être dans plusieurs catégories ; une seule est principale.
    """
    partenaire = models.ForeignKey(
        ProfilPartenaire,
        on_delete=models.CASCADE,
        related_name='liens_categories',
        verbose_name=_('commerçant'),
    )
    categorie = models.ForeignKey(
        Categorie,
        on_delete=models.CASCADE,
        related_name='liens_partenaires',
        verbose_name=_('catégorie'),
    )
    est_principale = models.BooleanField(_('catégorie principale'), default=False)

    class Meta:
        verbose_name = _('catégorie d\'un commerçant')
        verbose_name_plural = _('catégories des commerçants')
        constraints = [
            models.UniqueConstraint(
                fields=['partenaire', 'categorie'],
                name='unique_partenaire_categorie',
            ),
        ]

    def __str__(self):
        marqueur = ' ★' if self.est_principale else ''
        return f"{self.partenaire.nom_commerce} → {self.categorie.nom}{marqueur}"


# ═══════════════════════════════════════════════════════════════════════
# SECTIONS DE MENU (resto, fast-food)
# ═══════════════════════════════════════════════════════════════════════

class SectionMenu(models.Model):
    """
    Section d'un menu (Entrées, Burgers, Pizzas, Boissons…).
    Spécifique aux restaurants et fast-foods.
    """
    partenaire = models.ForeignKey(
        ProfilPartenaire,
        on_delete=models.CASCADE,
        related_name='sections_menu',
        verbose_name=_('commerçant'),
    )
    nom = models.CharField(_('nom de la section'), max_length=100)
    description = models.TextField(_('description'), blank=True)
    icone = models.CharField(_('icône'), max_length=50, blank=True)
    ordre = models.IntegerField(_('ordre d\'affichage'), default=0)
    est_active = models.BooleanField(_('section active'), default=True)

    class Meta:
        verbose_name = _('section de menu')
        verbose_name_plural = _('sections de menu')
        ordering = ['partenaire', 'ordre', 'nom']

    def __str__(self):
        return f"{self.partenaire.nom_commerce} — {self.nom}"


# ═══════════════════════════════════════════════════════════════════════
# ARTICLE (modèle central générique)
# ═══════════════════════════════════════════════════════════════════════

class Article(models.Model):
    """
    Modèle générique pour tout ce qu'un commerçant offre :
    produit, plat, service, logement, véhicule, modèle de couture…

    Les spécificités fortes (logement, véhicule) sont extensionnées via
    des tables séparées (Logement, Vehicule) en relation 1-1.
    Les détails légers (allergènes pour plats…) vont dans le JSONB `details`.
    """

    class Type(models.TextChoices):
        PRODUIT = 'produit', _('Produit')
        PLAT = 'plat', _('Plat')
        SERVICE = 'service', _('Service')
        LOGEMENT = 'logement', _('Logement')
        VEHICULE = 'vehicule', _('Véhicule')
        MODELE_COUTURE = 'modele_couture', _('Modèle de couture')
        MODELE_MENUISERIE = 'modele_menuiserie', _('Modèle de menuiserie')

    partenaire = models.ForeignKey(
        ProfilPartenaire,
        on_delete=models.CASCADE,
        related_name='articles',
        verbose_name=_('commerçant'),
    )
    categorie = models.ForeignKey(
        Categorie,
        on_delete=models.PROTECT,
        related_name='articles',
        verbose_name=_('catégorie'),
    )

    # ── Identité ─────────────────────────────────────────────────────
    nom = models.CharField(_('nom'), max_length=200)
    slug = models.SlugField(_('slug'), max_length=220)
    description = models.TextField(_('description'), blank=True)

    type = models.CharField(_('type'), max_length=30, choices=Type.choices)

    # ── Tarif ────────────────────────────────────────────────────────
    prix = models.DecimalField(
        _('prix (FCFA)'),
        max_digits=12, decimal_places=0,
        blank=True, null=True,
    )
    prix_promotion = models.DecimalField(
        _('prix promotionnel (FCFA)'),
        max_digits=12, decimal_places=0,
        blank=True, null=True,
    )
    unite = models.CharField(
        _('unité'),
        max_length=30,
        blank=True,
        help_text=_('Ex: "par séance", "par jour", "le kilo"…'),
    )

    # ── Détails spécifiques au vertical (JSONB) ──────────────────────
    details = models.JSONField(
        _('détails spécifiques'),
        default=dict, blank=True,
        help_text=_('Champs variables par type d\'article (allergènes, halal, etc.).'),
    )

    # ── Spécifique resto / fast-food ─────────────────────────────────
    section_menu = models.ForeignKey(
        SectionMenu,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='articles',
        verbose_name=_('section du menu'),
    )
    temps_preparation_min = models.IntegerField(
        _('temps de préparation (min)'),
        blank=True, null=True,
    )

    # ── État ─────────────────────────────────────────────────────────
    est_actif = models.BooleanField(_('article actif'), default=True)
    est_disponible = models.BooleanField(_('disponible'), default=True)
    est_en_promotion = models.BooleanField(_('en promotion'), default=False)

    # ── Compteurs dénormalisés (perf) ────────────────────────────────
    nb_vues = models.IntegerField(_('nombre de vues'), default=0)
    nb_likes = models.IntegerField(_('nombre de likes'), default=0)
    nb_commentaires = models.IntegerField(_('nombre de commentaires'), default=0)
    nb_favoris = models.IntegerField(_('nombre de favoris'), default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('article')
        verbose_name_plural = _('articles')
        ordering = ['-created_at']
        constraints = [
            # Slug unique par commerçant : deux commerçants peuvent avoir un "burger-classique",
            # mais pas le même commerçant qui aurait deux articles identiques.
            models.UniqueConstraint(
                fields=['partenaire', 'slug'],
                name='unique_article_partenaire_slug',
            ),
        ]
        indexes = [
            models.Index(fields=['categorie', 'est_actif']),
            models.Index(fields=['partenaire', 'est_actif']),
            models.Index(fields=['type']),
        ]

    def __str__(self):
        return f"{self.nom} ({self.partenaire.nom_commerce})"


# ═══════════════════════════════════════════════════════════════════════
# EXTENSIONS SPÉCIALISÉES (1-1 avec Article)
# ═══════════════════════════════════════════════════════════════════════

class Logement(models.Model):
    """Détails d'un article de type 'logement' (location maison, résidence)."""

    article = models.OneToOneField(
        Article,
        on_delete=models.CASCADE,
        related_name='logement',
        verbose_name=_('article'),
    )
    nb_chambres = models.IntegerField(_('nombre de chambres'), default=1)
    nb_sdb = models.IntegerField(_('nombre de salles de bain'), default=1)
    surface_m2 = models.IntegerField(_('surface (m²)'), blank=True, null=True)
    meuble = models.BooleanField(_('meublé'), default=False)
    duree_min_jours = models.IntegerField(
        _('durée minimale (jours)'),
        blank=True, null=True,
    )
    caution = models.DecimalField(
        _('caution (FCFA)'),
        max_digits=12, decimal_places=0,
        blank=True, null=True,
    )
    equipements = models.JSONField(
        _('équipements'),
        default=list, blank=True,
        help_text=_('Liste d\'équipements : ["wifi", "clim", "parking"…]'),
    )

    class Meta:
        verbose_name = _('logement')
        verbose_name_plural = _('logements')

    def __str__(self):
        return f"Logement: {self.article.nom}"


class Vehicule(models.Model):
    """Détails d'un article de type 'vehicule' (vente ou location)."""

    class Carburant(models.TextChoices):
        ESSENCE = 'essence', _('Essence')
        DIESEL = 'diesel', _('Diesel')
        HYBRIDE = 'hybride', _('Hybride')
        ELECTRIQUE = 'electrique', _('Électrique')

    class BoiteVitesse(models.TextChoices):
        MANUELLE = 'manuelle', _('Manuelle')
        AUTOMATIQUE = 'automatique', _('Automatique')

    class Mode(models.TextChoices):
        VENTE = 'vente', _('Vente')
        LOCATION = 'location', _('Location')
        LES_DEUX = 'les_deux', _('Vente ou location')

    article = models.OneToOneField(
        Article,
        on_delete=models.CASCADE,
        related_name='vehicule',
        verbose_name=_('article'),
    )
    marque = models.CharField(_('marque'), max_length=50)
    modele = models.CharField(_('modèle'), max_length=100)
    annee = models.IntegerField(_('année'), blank=True, null=True)
    kilometrage = models.IntegerField(_('kilométrage'), blank=True, null=True)
    carburant = models.CharField(
        _('carburant'), max_length=20,
        choices=Carburant.choices, blank=True,
    )
    boite_vitesse = models.CharField(
        _('boîte de vitesse'), max_length=20,
        choices=BoiteVitesse.choices, blank=True,
    )
    places = models.IntegerField(_('nombre de places'), blank=True, null=True)
    mode = models.CharField(
        _('mode (vente / location)'),
        max_length=20,
        choices=Mode.choices,
        default=Mode.VENTE,
    )

    class Meta:
        verbose_name = _('véhicule')
        verbose_name_plural = _('véhicules')

    def __str__(self):
        return f"Véhicule: {self.marque} {self.modele} ({self.article.nom})"


# ═══════════════════════════════════════════════════════════════════════
# PHOTOS & PANORAMAS
# ═══════════════════════════════════════════════════════════════════════

class ArticleImage(models.Model):
    """Photo d'un article. Le quota dépend du plan d'abonnement du commerçant."""

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_('article'),
    )
    image = models.ImageField(_('image'), upload_to='articles/')
    legende = models.CharField(_('légende'), max_length=200, blank=True)
    ordre = models.IntegerField(_('ordre'), default=0)
    est_principale = models.BooleanField(_('image principale'), default=False)
    est_active = models.BooleanField(_('image active'), default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('image d\'article')
        verbose_name_plural = _('images d\'articles')
        ordering = ['article', 'ordre']
        constraints = [
            # Une seule image principale par article
            models.UniqueConstraint(
                fields=['article'],
                condition=models.Q(est_principale=True),
                name='unique_image_principale_par_article',
            ),
        ]

    def __str__(self):
        return f"Image {self.ordre} de {self.article.nom}"


class Panorama(models.Model):
    """
    Vue panoramique 360° d'un article (typiquement un logement / hôtel).
    L'image doit être équirectangulaire au ratio 2:1.
    """
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='panoramas',
        verbose_name=_('article'),
    )
    image = models.ImageField(_('image panoramique 360°'), upload_to='panoramas/')
    nom_piece = models.CharField(
        _('nom de la pièce'),
        max_length=100,
        blank=True,
        help_text=_('Ex: "Salon", "Chambre principale", "Cuisine"…'),
    )
    ordre = models.IntegerField(_('ordre'), default=0)
    est_active = models.BooleanField(_('panorama actif'), default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('panorama 360°')
        verbose_name_plural = _('panoramas 360°')
        ordering = ['article', 'ordre']

    def __str__(self):
        return f"Panorama {self.nom_piece or self.ordre} — {self.article.nom}"


# ═══════════════════════════════════════════════════════════════════════
# VARIANTES & SUPPLÉMENTS (resto, fast-food)
# ═══════════════════════════════════════════════════════════════════════

class Variante(models.Model):
    """
    Déclinaison d'un article (Petit / Moyen / Grand).
    Le client choisit exactement UNE variante par article.
    """
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='variantes',
        verbose_name=_('article'),
    )
    nom = models.CharField(_('nom'), max_length=50)
    prix_supplement = models.DecimalField(
        _('supplément de prix (FCFA)'),
        max_digits=10, decimal_places=0,
        default=0,
        help_text=_('S\'ajoute au prix de base de l\'article.'),
    )
    est_par_defaut = models.BooleanField(_('variante par défaut'), default=False)
    ordre = models.IntegerField(_('ordre'), default=0)
    est_active = models.BooleanField(_('variante active'), default=True)

    class Meta:
        verbose_name = _('variante')
        verbose_name_plural = _('variantes')
        ordering = ['article', 'ordre']
        constraints = [
            # Une seule variante par défaut par article
            models.UniqueConstraint(
                fields=['article'],
                condition=models.Q(est_par_defaut=True),
                name='unique_variante_par_defaut',
            ),
        ]

    def __str__(self):
        return f"{self.article.nom} — {self.nom}"


class Supplement(models.Model):
    """
    Supplément d'un article (Fromage, Frites, Sauce supplémentaire…).
    Le client peut en choisir plusieurs.
    """
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='supplements',
        verbose_name=_('article'),
    )
    nom = models.CharField(_('nom'), max_length=50)
    prix = models.DecimalField(
        _('prix (FCFA)'),
        max_digits=10, decimal_places=0,
        default=0,
    )
    est_optionnel = models.BooleanField(_('optionnel'), default=True)
    ordre = models.IntegerField(_('ordre'), default=0)
    est_actif = models.BooleanField(_('supplément actif'), default=True)

    class Meta:
        verbose_name = _('supplément')
        verbose_name_plural = _('suppléments')
        ordering = ['article', 'ordre']

    def __str__(self):
        return f"{self.article.nom} + {self.nom}"


# ═══════════════════════════════════════════════════════════════════════
# TRACKING DES VUES (Module 8 — Analytics, intégré au MVP)
# ═══════════════════════════════════════════════════════════════════════

class VueArticle(models.Model):
    """
    Trace chaque consultation d'un article par un utilisateur.
    Permet au commerçant de voir le nombre de vues par période,
    et alimente les stats globales d'analytics.
    """

    class Source(models.TextChoices):
        RECHERCHE = 'recherche', _('Recherche')
        CATEGORIE = 'categorie', _('Liste de catégorie')
        CARROUSEL = 'carrousel', _('Carrousel d\'accueil')
        FAVORIS = 'favoris', _('Liste des favoris')
        CHAT = 'chat', _('Lien depuis un chat')
        LIEN_DIRECT = 'lien_direct', _('Lien direct / partage')
        AUTRE = 'autre', _('Autre')

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name='vues',
        verbose_name=_('article'),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name='vues_articles',
        verbose_name=_('utilisateur'),
        help_text=_('Peut être nul si l\'utilisateur n\'est pas authentifié.'),
    )
    date_vue = models.DateTimeField(_('date de la vue'), auto_now_add=True)
    source = models.CharField(
        _('source'),
        max_length=20,
        choices=Source.choices,
        default=Source.AUTRE,
    )
    duree_secondes = models.IntegerField(
        _('durée de consultation (s)'),
        blank=True, null=True,
        help_text=_('Combien de temps l\'utilisateur est resté sur la fiche.'),
    )

    class Meta:
        verbose_name = _('vue d\'article')
        verbose_name_plural = _('vues d\'articles')
        ordering = ['-date_vue']
        indexes = [
            models.Index(fields=['article', '-date_vue']),
            models.Index(fields=['user', '-date_vue']),
        ]

    def __str__(self):
        qui = self.user.telephone if self.user else 'anonyme'
        return f"{qui} a vu {self.article.nom} le {self.date_vue:%d/%m/%Y %H:%M}"