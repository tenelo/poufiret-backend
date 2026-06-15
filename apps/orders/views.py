"""Vues panier (Module 4 - bloc A1)."""
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.catalog.models import Article, Variante, Supplement
from .models import Panier, LignePanier
from .serializers import PanierSerializer


class MesPaniersView(APIView):
    """GET /orders/paniers/ — tous les paniers du client (1 par partenaire)."""
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        paniers = (Panier.objects.filter(user=request.user)
                   .select_related('partenaire').prefetch_related('lignes__article'))
        return Response(PanierSerializer(paniers, many=True, context={'request': request}).data)


class AjouterLigneView(APIView):
    """POST /orders/paniers/ajouter/ — ajoute un article au panier du bon partenaire.
    Body: article (id), quantite, variante_id?, supplement_ids?[], note_speciale?"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        article = get_object_or_404(Article, pk=request.data.get('article'), est_actif=True)
        quantite = int(request.data.get('quantite', 1))
        if quantite < 1:
            return Response({'erreur': True, 'message': 'Quantité invalide.'}, status=400)

        # Panier du partenaire de cet article (créé si absent)
        panier, _ = Panier.objects.get_or_create(user=request.user, partenaire=article.partenaire)

        # Prix unitaire = prix article (promo si active) + variante
        prix = article.prix_promotion if (article.est_en_promotion and article.prix_promotion) else article.prix
        prix = prix or 0
        variante_id = request.data.get('variante_id')
        if variante_id:
            v = Variante.objects.filter(pk=variante_id, article=article).first()
            if v:
                prix += v.prix_supplement

        # Snapshot des suppléments choisis
        supp_ids = request.data.get('supplement_ids', []) or []
        supplements = [
            {'id': s.id, 'nom': s.nom, 'prix': int(s.prix)}
            for s in Supplement.objects.filter(pk__in=supp_ids, article=article)
        ]

        ligne = LignePanier.objects.create(
            panier=panier, article=article, variante_id=variante_id or None,
            supplements=supplements, quantite=quantite, prix_unitaire=prix,
            note_speciale=request.data.get('note_speciale', ''),
        )
        panier.refresh_from_db()
        return Response(PanierSerializer(panier, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class LigneDetailView(APIView):
    """PATCH/DELETE /orders/lignes/<id>/ — modifier quantité/note ou retirer une ligne."""
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk):
        return get_object_or_404(LignePanier, pk=pk, panier__user=request.user)

    def patch(self, request, pk=None):
        ligne = self._get(request, pk)
        if 'quantite' in request.data:
            q = int(request.data['quantite'])
            if q < 1:
                return Response({'erreur': True, 'message': 'Quantité invalide.'}, status=400)
            ligne.quantite = q
        if 'note_speciale' in request.data:
            ligne.note_speciale = request.data['note_speciale']
        ligne.save()
        return Response(PanierSerializer(ligne.panier, context={'request': request}).data)

    def delete(self, request, pk=None):
        ligne = self._get(request, pk)
        panier = ligne.panier
        ligne.delete()
        if not panier.lignes.exists():
            panier.delete()
            return Response({'message': 'Panier vide et supprimé.'}, status=status.HTTP_200_OK)
        return Response(PanierSerializer(panier, context={'request': request}).data)


class ViderPanierView(APIView):
    """DELETE /orders/paniers/<id>/ — vide et supprime un panier."""
    permission_classes = [permissions.IsAuthenticated]
    def delete(self, request, pk=None):
        panier = get_object_or_404(Panier, pk=pk, user=request.user)
        panier.delete()
        return Response({'message': 'Panier vidé.'}, status=status.HTTP_200_OK)
