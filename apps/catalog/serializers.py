"""Serializers du module Catalogue."""
from rest_framework import serializers
from .models import (
    Categorie, Article, ArticleImage, ArticleVideo, SectionMenu, Variante, Supplement,
    GroupeOption, OptionGroupe,
    Panorama, Logement, Vehicule, annoter_nb_partenaires,
)


class CategorieSerializer(serializers.ModelSerializer):
    enfants = serializers.SerializerMethodField()
    nb_partenaires = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = ['id', 'nom', 'slug', 'description', 'icone', 'image_couverture',
                  'parent', 'mode_transaction', 'types_articles', 'affiche_catalogue', 'module_flutter', 'ordre',
                  'est_active', 'nb_partenaires', 'enfants',
                  'types_partenaire']

    @staticmethod
    def _enfants_actifs(obj):
        """Enfants actifs annotes et tries : lus depuis le prefetch
        (prefetch_enfants_actifs, 0 requete) quand il est present, sinon
        requete directe (detail hors viewset, niveaux au-dela du prefetch)."""
        pre = getattr(obj, 'enfants_actifs', None)
        if pre is None:
            pre = list(annoter_nb_partenaires(
                obj.enfants.filter(est_active=True)).order_by('ordre', 'nom'))
            obj.enfants_actifs = pre  # evite de relire pour nb_partenaires
        return pre

    def get_nb_partenaires(self, obj):
        # Categorie "groupe" (a des enfants actifs) : l'app ne s'en sert pas,
        # elle se base sur le nb_partenaires de chaque enfant. On renvoie
        # explicitement null plutôt qu'un total pour ne pas laisser croire
        # que c'est un decompte direct de partenaires sur le groupe lui-même.
        if self._enfants_actifs(obj):
            return None
        a = getattr(obj, 'nb_via_liaison', None)
        b = getattr(obj, 'nb_via_articles', None)
        if a is None and b is None:
            return None  # contexte sans annotation
        return max(a or 0, b or 0)

    def get_enfants(self, obj):
        return CategorieSerializer(
            self._enfants_actifs(obj), many=True, context=self.context).data


class SectionMenuSerializer(serializers.ModelSerializer):
    """Section de carte (« Grillades », « Boissons »…). Réutilisée par les
    deux périmètres de gestion (restaurateur / admin, apps.restaurants.
    views_carte) — le partenaire est toujours injecté par la vue."""
    class Meta:
        model = SectionMenu
        fields = ['id', 'partenaire', 'nom', 'description', 'icone', 'ordre', 'est_active',
                  'modifie_par_role', 'modifie_par_nom', 'modifie_le']
        read_only_fields = ['partenaire', 'modifie_par_role', 'modifie_par_nom', 'modifie_le']


class ArticleImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleImage
        fields = ['id', 'article', 'image', 'legende', 'ordre', 'est_principale', 'est_active']
        read_only_fields = ['est_active']


class VarianteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variante
        fields = ['id', 'article', 'nom', 'prix_supplement', 'est_par_defaut', 'ordre', 'est_active']


class SupplementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplement
        fields = ['id', 'article', 'nom', 'prix', 'est_optionnel', 'ordre', 'est_actif']


class OptionGroupeSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionGroupe
        fields = ['id', 'groupe', 'nom', 'prix_supplement', 'ordre', 'est_actif']


class GroupeOptionSerializer(serializers.ModelSerializer):
    """Groupe d'options d'un article (« Garniture », « Suppléments »…),
    avec ses options imbriquées en lecture (écriture via OptionViewSet,
    /catalogue/options/?groupe=<id>, même pattern que variantes/supplements)."""
    options = OptionGroupeSerializer(many=True, read_only=True)

    class Meta:
        model = GroupeOption
        fields = ['id', 'article', 'libelle', 'min_choix', 'max_choix',
                  'ordre', 'est_actif', 'options']

    def validate(self, attrs):
        mini = attrs.get('min_choix', getattr(self.instance, 'min_choix', 0))
        maxi = attrs.get('max_choix', getattr(self.instance, 'max_choix', None))
        if maxi is not None and maxi < mini:
            raise serializers.ValidationError(
                {'max_choix': 'Doit être supérieur ou égal à min_choix (ou vide).'})
        return attrs


class PanoramaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Panorama
        fields = ['id', 'article', 'image', 'nom_piece', 'ordre', 'est_active']


class LogementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Logement
        fields = ['id', 'article', 'nb_chambres', 'nb_sdb', 'surface_m2', 'meuble',
                  'duree_min_jours', 'caution', 'equipements']
        read_only_fields = ['article']


class VehiculeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicule
        fields = ['id', 'article', 'marque', 'modele', 'annee', 'kilometrage',
                  'carburant', 'boite_vitesse', 'places', 'mode']
        read_only_fields = ['article']


class ArticleListeSerializer(serializers.ModelSerializer):
    image_principale = serializers.SerializerMethodField()
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    pourcentage_reduction = serializers.ReadOnlyField()
    prix_effectif = serializers.ReadOnlyField()
    promotion_valide = serializers.ReadOnlyField()

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'type', 'prix', 'prix_promotion',
                  'pourcentage_reduction', 'prix_effectif', 'promotion_valide',
                  'est_en_promotion', 'est_disponible', 'nb_vues', 'nb_likes',
                  'partenaire', 'partenaire_nom', 'categorie', 'image_principale']

    def get_image_principale(self, obj):
        img = (obj.images.filter(est_principale=True, est_active=True).first()
               or obj.images.filter(est_active=True).first())
        if img and img.image:
            req = self.context.get('request')
            return req.build_absolute_uri(img.image.url) if req else img.image.url
        return None

class ArticleVideoSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)
    article_slug = serializers.CharField(source='article.slug', read_only=True)
    class Meta:
        model = ArticleVideo
        fields = ['id', 'article', 'article_nom', 'article_slug', 'video',
                  'titre', 'miniature', 'ordre', 'est_active']
        read_only_fields = ['id']


class ArticleDetailSerializer(serializers.ModelSerializer):
    images = ArticleImageSerializer(many=True, read_only=True)
    videos = ArticleVideoSerializer(many=True, read_only=True)
    variantes = VarianteSerializer(many=True, read_only=True)
    supplements = SupplementSerializer(many=True, read_only=True)
    panoramas = PanoramaSerializer(many=True, read_only=True)
    logement = LogementSerializer(read_only=True)
    vehicule = VehiculeSerializer(read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    est_like_par_moi = serializers.SerializerMethodField()
    est_favori_par_moi = serializers.SerializerMethodField()
    pourcentage_reduction = serializers.ReadOnlyField()
    prix_effectif = serializers.ReadOnlyField()
    promotion_valide = serializers.ReadOnlyField()

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'description', 'type', 'prix', 'prix_promotion',
                  'unite', 'details', 'est_actif', 'est_disponible', 'est_en_promotion',
                  'pourcentage_reduction', 'prix_effectif', 'promotion_valide',
                  'temps_preparation_min', 'nb_vues', 'nb_likes', 'nb_commentaires',
                  'nb_favoris', 'partenaire', 'partenaire_nom', 'categorie', 'section_menu',
                  'images', 'videos', 'variantes', 'supplements', 'panoramas', 'logement', 'vehicule',
                  'est_like_par_moi', 'est_favori_par_moi',
                  'created_at', 'updated_at']
        read_only_fields = ['slug', 'nb_vues', 'nb_likes', 'nb_commentaires',
                            'nb_favoris', 'partenaire']

    def _user(self):
        req = self.context.get('request')
        if req and req.user and req.user.is_authenticated:
            return req.user
        return None

    def get_est_like_par_moi(self, obj):
        user = self._user()
        if user is None:
            return False
        return obj.likes.filter(user=user).exists()

    def get_est_favori_par_moi(self, obj):
        user = self._user()
        if user is None:
            return False
        return obj.favoris.filter(user=user).exists()


class ArticleCarteGestionSerializer(serializers.ModelSerializer):
    """Plat de la carte, pour la gestion restaurateur/admin (mêmes vues,
    périmètre seul différent — apps.restaurants.views_carte). Réutilise les
    sous-serializers existants (images, variantes, groupes d'options) sans
    duplication ; leur écriture se fait via leurs propres endpoints
    (plats/<id>/images/, variantes/?plat=, groupes-options/?plat=)."""
    images = ArticleImageSerializer(many=True, read_only=True)
    variantes = VarianteSerializer(many=True, read_only=True)
    groupes_options = GroupeOptionSerializer(many=True, read_only=True)
    section_menu_nom = serializers.CharField(source='section_menu.nom', read_only=True)
    est_epuise = serializers.SerializerMethodField()
    prix_effectif = serializers.ReadOnlyField()
    modifie_le = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'description', 'categorie', 'section_menu',
                  'section_menu_nom', 'prix', 'prix_promotion', 'prix_effectif',
                  'est_en_promotion', 'est_actif', 'est_disponible', 'est_epuise',
                  'est_reserve_aux_menus', 'ordre', 'temps_preparation_min', 'details',
                  'images', 'variantes', 'groupes_options', 'partenaire',
                  'modifie_par_role', 'modifie_par_nom', 'modifie_le']
        read_only_fields = ['slug', 'partenaire', 'modifie_par_role', 'modifie_par_nom']
        extra_kwargs = {'categorie': {'required': False}}

    def get_est_epuise(self, obj):
        return not obj.est_disponible