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


from django.db import transaction
from django.utils import timezone
from datetime import datetime
from .models import Commande, LigneCommande
from .serializers import CommandeSerializer

# Transitions autorisées du workflow
TRANSITIONS = {
    'nouvelle': ['acceptee', 'refusee', 'annulee'],
    'acceptee': ['en_preparation', 'annulee'],
    'en_preparation': ['prete', 'annulee'],
    'prete': ['en_livraison', 'livree', 'expiree'],
    'en_livraison': ['livree'],
    'livree': [],
    'refusee': [],
    'annulee': [],
    'expiree': [],
}


def _numero_commande():
    annee = datetime.now().year
    n = Commande.objects.filter(numero__startswith=f'PFR-{annee}-').count() + 1
    return f'PFR-{annee}-{n:05d}'


class ValiderPanierView(APIView):
    """POST /orders/paniers/<id>/valider/ — transforme un panier en commande.
    Body: mode_livraison?, adresse?(id), heure_souhaitee?, mode_paiement?, notes_client?, frais_livraison?"""
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk=None):
        panier = get_object_or_404(Panier, pk=pk, user=request.user)
        lignes = list(panier.lignes.select_related('article'))
        if not lignes:
            return Response({'erreur': True, 'message': 'Panier vide.'}, status=400)

        sous_total = 0
        for l in lignes:
            supp = sum(s.get('prix', 0) for s in (l.supplements or []))
            sous_total += (l.prix_unitaire + supp) * l.quantite
        frais = int(request.data.get('frais_livraison', 0) or 0)

        adresse_id = request.data.get('adresse')
        adresse_obj, adresse_snap = None, ''
        if adresse_id:
            from apps.users.models import AdresseClient
            adresse_obj = AdresseClient.objects.filter(pk=adresse_id, user=request.user).first()
            if adresse_obj:
                adresse_snap = adresse_obj.adresse

        commande = Commande.objects.create(
            numero=_numero_commande(), user=request.user, partenaire=panier.partenaire,
            mode_livraison=request.data.get('mode_livraison', 'emporter'),
            adresse=adresse_obj, adresse_snapshot=adresse_snap,
            heure_souhaitee=request.data.get('heure_souhaitee') or None,
            mode_paiement=request.data.get('mode_paiement', 'cash'),
            notes_client=request.data.get('notes_client', ''),
            sous_total=sous_total, frais_livraison=frais, total=sous_total + frais,
        )
        # Snapshots des lignes
        from apps.catalog.models import Variante
        for l in lignes:
            supp = sum(s.get('prix', 0) for s in (l.supplements or []))
            v_nom = ''
            if l.variante_id:
                v = Variante.objects.filter(pk=l.variante_id).first()
                v_nom = v.nom if v else ''
            LigneCommande.objects.create(
                commande=commande, article=l.article, nom_article=l.article.nom,
                variante_nom=v_nom, supplements=l.supplements, quantite=l.quantite,
                prix_unitaire=l.prix_unitaire, prix_ligne=(l.prix_unitaire + supp) * l.quantite,
                note_speciale=l.note_speciale,
            )
        panier.delete()  # vide le panier
        return Response(CommandeSerializer(commande, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


class MesCommandesClientView(APIView):
    """GET /orders/commandes/ — commandes du client connecté."""
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        qs = (Commande.objects.filter(user=request.user)
              .select_related('partenaire').prefetch_related('lignes'))
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)
        return Response(CommandeSerializer(qs, many=True, context={'request': request}).data)


class CommandesPartenaireView(APIView):
    """GET /orders/commandes/partenaire/ — commandes reçues par le partenaire connecté."""
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if not hasattr(request.user, 'profil_partenaire'):
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'}, status=403)
        qs = (Commande.objects.filter(partenaire=request.user.profil_partenaire)
              .select_related('user').prefetch_related('lignes'))
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)
        return Response(CommandeSerializer(qs, many=True, context={'request': request}).data)


class CommandeDetailView(APIView):
    """GET /orders/commandes/<id>/ — détail (client propriétaire OU partenaire concerné)."""
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request, pk=None):
        c = get_object_or_404(Commande, pk=pk)
        u = request.user
        est_client = c.user_id == u.id
        est_part = hasattr(u, 'profil_partenaire') and c.partenaire_id == u.profil_partenaire.id
        if not (est_client or est_part):
            return Response({'erreur': True, 'message': 'Accès refusé.'}, status=403)
        return Response(CommandeSerializer(c, context={'request': request}).data)


class TransitionCommandeView(APIView):
    """POST /orders/commandes/<id>/transition/ — change le statut selon le workflow.
    Body: statut (cible), raison_refus? Le partenaire gère accept/refus/prepa/prete/livraison;
    le client peut annuler une commande encore 'nouvelle'."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        c = get_object_or_404(Commande, pk=pk)
        u = request.user
        cible = request.data.get('statut')
        est_client = c.user_id == u.id
        est_part = hasattr(u, 'profil_partenaire') and c.partenaire_id == u.profil_partenaire.id
        if not (est_client or est_part):
            return Response({'erreur': True, 'message': 'Accès refusé.'}, status=403)

        if cible not in TRANSITIONS.get(c.statut, []):
            return Response({'erreur': True,
                'message': f"Transition {c.statut} → {cible} non autorisée."}, status=400)

        # Le client ne peut qu'annuler une commande 'nouvelle'
        if est_client and not est_part:
            if not (c.statut == 'nouvelle' and cible == 'annulee'):
                return Response({'erreur': True,
                    'message': "En tant que client, vous ne pouvez qu'annuler une commande non encore acceptée."}, status=403)

        c.statut = cible
        now = timezone.now()
        if cible == 'acceptee': c.acceptee_le = now
        elif cible == 'prete': c.prete_le = now
        elif cible == 'livree': c.livree_le = now
        elif cible == 'refusee': c.raison_refus = request.data.get('raison_refus', '')
        elif cible == 'annulee': c.annulee_par = u
        c.save()
        return Response(CommandeSerializer(c, context={'request': request}).data)
