"""Serializers panier (Module 4 - bloc A1)."""
from rest_framework import serializers # type: ignore
from apps.catalog.models import Article, Variante, Supplement
from .models import Panier, LignePanier


class LignePanierSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)
    prix_ligne = serializers.SerializerMethodField()

    class Meta:
        model = LignePanier
        fields = ['id', 'article', 'article_nom', 'variante_id', 'supplements',
                  'quantite', 'prix_unitaire', 'prix_ligne', 'note_speciale', 'created_at']
        read_only_fields = ['prix_unitaire']

    def get_prix_ligne(self, obj):
        supp = sum(s.get('prix', 0) for s in (obj.supplements or []))
        return (obj.prix_unitaire + supp) * obj.quantite


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
    class Meta:
        model = LigneCommande
        fields = ['id', 'article', 'nom_article', 'variante_nom', 'supplements',
                  'quantite', 'prix_unitaire', 'prix_ligne', 'note_speciale']


class CommandeSerializer(serializers.ModelSerializer):
    lignes = LigneCommandeSerializer(many=True, read_only=True)
    partenaire_nom = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    client_nom = serializers.SerializerMethodField()

    class Meta:
        model = Commande
        fields = ['id', 'numero', 'user', 'client_nom', 'partenaire', 'partenaire_nom',
                  'mode_livraison', 'adresse', 'adresse_snapshot', 'heure_souhaitee',
                  'statut', 'raison_refus', 'sous_total', 'frais_livraison', 'total',
                  'mode_paiement', 'notes_client', 'notes_partenaire', 'lignes',
                  'created_at', 'acceptee_le', 'prete_le', 'livree_le']
        read_only_fields = ['numero', 'user', 'partenaire', 'statut', 'sous_total', 'total']

    def get_client_nom(self, obj):
        return obj.user.get_full_name() or obj.user.username or obj.user.telephone
