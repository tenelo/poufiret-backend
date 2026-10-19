"""Serializers panier (Module 4 - bloc A1)."""
from rest_framework import serializers # type: ignore
from apps.catalog.models import Article, Variante, Supplement
from .models import Panier, LignePanier


def _image_article(article, context):
    """URL absolue de l'image principale de l'article (même règle que la carte
    restaurant : principale active, sinon 1re active par ordre), ou None.
    Lit article.images.all() : préchargé par les vues (0 requête par ligne)."""
    if article is None:
        return None
    from apps.restaurants.serializers import url_image_plat
    return url_image_plat(article, context.get('request'))


class LignePanierSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)
    image = serializers.SerializerMethodField()
    prix_ligne = serializers.SerializerMethodField()
    variante_nom = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    class Meta:
        model = LignePanier
        fields = ['id', 'article', 'article_nom', 'image', 'variante_id', 'variante_nom',
                  'supplements', 'options', 'ligne_menu', 'quantite', 'prix_unitaire',
                  'prix_ligne', 'note_speciale', 'created_at']
        read_only_fields = ['prix_unitaire']

    def get_image(self, obj):
        return _image_article(obj.article, self.context)

    def get_prix_ligne(self, obj):
        supp = sum(s.get('prix', 0) for s in (obj.supplements or []))
        return (obj.prix_unitaire + supp) * obj.quantite

    def get_variante_nom(self, obj):
        if not obj.variante_id:
            return None
        return Variante.objects.filter(pk=obj.variante_id).values_list('nom', flat=True).first()

    def get_options(self, obj):
        return [{'nom': s.get('nom', ''), 'prix_supplement': s.get('prix', 0)}
                for s in (obj.supplements or [])]


class PanierSerializer(serializers.ModelSerializer):
    lignes = LignePanierSerializer(many=True, read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    categorie_nom = serializers.CharField(source='categorie.nom', read_only=True)
    total = serializers.SerializerMethodField()
    
    class Meta:
            model = Panier
            fields = ['id', 'partenaire', 'partenaire_nom', 'categorie', 'categorie_nom',
                    'lignes', 'total', 'created_at', 'updated_at']

    def get_total(self, obj):
        
        t = 0
        for l in obj.lignes.all():
            supp = sum(s.get('prix', 0) for s in (l.supplements or []))
            t += (l.prix_unitaire + supp) * l.quantite
        return t


from .models import Commande, LigneCommande


class LigneCommandeSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = LigneCommande
        fields = ['id', 'article', 'nom_article', 'image', 'variante_nom', 'supplements',
                  'quantite', 'prix_unitaire', 'prix_ligne', 'note_speciale']

    def get_image(self, obj):
        """null si l'article a été supprimé depuis la commande (article SET_NULL)."""
        return _image_article(obj.article, self.context)


class CommandeSerializer(serializers.ModelSerializer):
    lignes = LigneCommandeSerializer(many=True, read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    client_nom = serializers.SerializerMethodField()
    client_telephone = serializers.CharField(source='user.telephone', read_only=True)

    class Meta:
        model = Commande
        fields = ['id', 'numero', 'user', 'client_nom', 'client_telephone', 'partenaire', 'partenaire_nom',
                  'mode_livraison', 'adresse', 'adresse_snapshot', 'heure_souhaitee',
                  'statut', 'raison_refus', 'sous_total', 'frais_livraison', 'total',
                  'mode_paiement', 'notes_client', 'notes_partenaire', 'lignes',
                  'created_at', 'acceptee_le', 'prete_le', 'livree_le']
        read_only_fields = ['numero', 'user', 'partenaire', 'statut', 'sous_total', 'total']

    def get_client_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone
