"""Vues panier (Module 4 - bloc A1)."""
from datetime import datetime

from django.contrib.gis.geos import Point # type: ignore
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.catalog.models import Article, Variante, Supplement
from .models import Panier, LignePanier
from .serializers import PanierSerializer
from apps.notifications.fcm import notifier_utilisateur
from apps.livraison.models import Course
from apps.livraison.views import _numero as _numero_course, finaliser_assignation


def _parser_date(valeur):
    """Parse une date 'YYYY-MM-DD'. Retourne None si absente ou invalide
    (jamais d'exception — un paramètre mal formé est simplement ignoré)."""
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


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

        # Panier pur (partenaire + catégorie de cet article), créé si absent
        panier, _ = Panier.objects.get_or_create(
            user=request.user,
            partenaire=article.partenaire,
            categorie=article.categorie,
        )
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

        # ── Point GPS de livraison (obligatoire si livraison) ──
        mode_liv = request.data.get('mode_livraison', 'emporter')
        point_livraison = None
        if mode_liv == 'livraison':
            lat = request.data.get('latitude')
            lng = request.data.get('longitude')
            if lat in (None, '') or lng in (None, ''):
                return Response(
                    {'erreur': True,
                     'message': 'Position GPS obligatoire pour une livraison.'},
                    status=400)
            try:
                point_livraison = Point(float(lng), float(lat))
            except (TypeError, ValueError):
                return Response(
                    {'erreur': True, 'message': 'Coordonnées GPS invalides.'},
                    status=400)

        commande = Commande.objects.create(
            numero=_numero_commande(), user=request.user, partenaire=panier.partenaire,
            mode_livraison=mode_liv,
            localisation_livraison=point_livraison,
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
    """GET /orders/commandes/partenaire/ — commandes reçues par le partenaire connecté.

    Filtres optionnels (en plus de ?statut=) :
    - ?date=today : commandes créées aujourd'hui (date du serveur).
    - ?debut=YYYY-MM-DD&fin=YYYY-MM-DD : intervalle de création (bornes
      incluses), debut et fin peuvent être fournis seuls. Un paramètre
      mal formé est ignoré (pas d'erreur), pas de filtrage sur ce champ.
    Sans aucun de ces paramètres : comportement inchangé.
    """
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if not hasattr(request.user, 'profil_partenaire'):
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'}, status=403)
        qs = (Commande.objects.filter(partenaire=request.user.profil_partenaire)
              .select_related('user').prefetch_related('lignes'))
        s = request.query_params.get('statut')
        if s: qs = qs.filter(statut=s)

        if request.query_params.get('date') == 'today':
            qs = qs.filter(created_at__date=timezone.localdate())
        else:
            debut = _parser_date(request.query_params.get('debut'))
            fin = _parser_date(request.query_params.get('fin'))
            if debut:
                qs = qs.filter(created_at__date__gte=debut)
            if fin:
                qs = qs.filter(created_at__date__lte=fin)

        return Response(CommandeSerializer(qs, many=True, context={'request': request}).data)


class ResumeCommandesPartenaireView(APIView):
    """GET /orders/commandes/partenaire/resume/ — compteur léger pour la
    cloche de notification (pensé pour un polling fréquent côté front).

    Filtres optionnels identiques à CommandesPartenaireView (?date=today,
    ?debut=YYYY-MM-DD&fin=YYYY-MM-DD) : quand fournis, nouvelles/
    en_preparation/acceptees/total/ca portent sur la période demandée —
    de quoi afficher une seconde rangée de cartes filtrées, en plus de
    l'appel sans paramètre (compteurs globaux, comportement inchangé).
    total_aujourdhui reste toujours global (snapshot du jour).
    """
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        if not hasattr(request.user, 'profil_partenaire'):
            return Response({'erreur': True, 'message': 'Réservé aux partenaires.'}, status=403)
        qs = Commande.objects.filter(partenaire=request.user.profil_partenaire)

        qs_periode = qs
        if request.query_params.get('date') == 'today':
            qs_periode = qs_periode.filter(created_at__date=timezone.localdate())
        else:
            debut = _parser_date(request.query_params.get('debut'))
            fin = _parser_date(request.query_params.get('fin'))
            if debut:
                qs_periode = qs_periode.filter(created_at__date__gte=debut)
            if fin:
                qs_periode = qs_periode.filter(created_at__date__lte=fin)

        ca = qs_periode.filter(statut=Commande.Statut.LIVREE).aggregate(
            total=Sum('total'))['total'] or 0

        return Response({
            'nouvelles': qs_periode.filter(statut=Commande.Statut.NOUVELLE).count(),
            'en_preparation': qs_periode.filter(statut=Commande.Statut.EN_PREPARATION).count(),
            'acceptees': qs_periode.filter(statut=Commande.Statut.ACCEPTEE).count(),
            'total_aujourdhui': qs.filter(created_at__date=timezone.localdate()).count(),
            'total': qs_periode.count(),
            'ca': ca,
        })


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


_LIBELLES_COMMANDE = {
    'acceptee': 'a ete acceptee',
    'refusee': 'a ete refusee',
    'en_preparation': 'est en preparation',
    'prete': 'est prete',
    'en_livraison': 'est en livraison',
    'livree': 'a ete livree',
}


def _notifier_transition_commande(commande, cible, acteur_est_client, request):
    """Notifie la bonne partie apres un changement de statut de commande."""
    num = commande.numero
    if cible == 'annulee' and acteur_est_client:
        # Le client a annule -> on previent le partenaire.
        dest = getattr(commande.partenaire, 'user', None)
        if dest:
            notifier_utilisateur(
                dest, 'Commande annulee',
                f'La commande {num} a ete annulee par le client.',
                data={'type': 'commande', 'id': str(commande.id)}, request=request)
        return
    libelle = _LIBELLES_COMMANDE.get(cible)
    if libelle:
        # Transition faite par le partenaire -> on previent le client.
        notifier_utilisateur(
            commande.user, 'Suivi de commande',
            f'Votre commande {num} {libelle}.',
            data={'type': 'commande', 'id': str(commande.id)}, request=request)


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
        _notifier_transition_commande(c, cible, est_client and not est_part, request)
        return Response(CommandeSerializer(c, context={'request': request}).data)


class CommanderLivreurView(APIView):
    """POST /orders/commandes/<pk>/livreur/ — le partenaire proprietaire
    declenche une course de livraison pour une commande prete.

    Cree la course (A = partenaire, B = client), herite du prix
    (frais_livraison), tente l'assignation, puis passe la commande en
    livraison. Point B = localisation_livraison capturee au checkout.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk=None):
        commande = get_object_or_404(Commande, pk=pk)

        # ── Garde 1 : proprietaire ──
        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None or commande.partenaire_id != profil.pk:
            return Response(
                {'erreur': True, 'message': "Vous n'etes pas le partenaire de cette commande."},
                status=403)

        # ── Garde 2 : mode livraison ──
        if commande.mode_livraison != 'livraison':
            return Response(
                {'erreur': True, 'message': "Cette commande n'est pas en mode livraison."},
                status=400)

        # ── Garde 4 : pas de course active ──
        course_active = commande.courses.exclude(
            statut__in=['annulee', 'refusee']).order_by('-cree_le').first()
        if course_active is not None:
            return Response(
                {'erreur': True, 'message': "Une course est deja en cours pour cette commande.",
                 'course_numero': course_active.numero},
                status=409)

        # ── Garde 3 : statut prete ──
        if commande.statut != Commande.Statut.PRETE:
            return Response(
                {'erreur': True,
                 'message': "La commande doit etre prete avant d'appeler un livreur."},
                status=400)

        # ── Garde 5 : GPS partenaire (point A) present ──
        if profil.localisation is None:
            return Response(
                {'erreur': True,
                 'message': "Votre commerce n'a pas de position GPS. Renseignez-la d'abord."},
                status=400)

        # ── Creation de la course ──
        client = commande.user
        course = Course.objects.create(
            numero=_numero_course(),
            demandeur=request.user,
            type_demandeur='partenaire',
            ville=profil.departement,
            commande=commande,
            contact_user=client,  # destinataire connu : pas de lookup async
            # Point A = partenaire (retrait)
            a_quartier=profil.quartier or profil.nom_commerce,
            a_nom_contact=profil.nom_commerce,
            a_telephone_contact=profil.telephone_pro or request.user.telephone,
            a_position=profil.localisation,
            # Point B = client (livraison)
            b_quartier=commande.adresse_snapshot or '—',
            b_nom_contact=client.get_full_name() or client.telephone,
            b_telephone_contact=client.telephone,
            b_position=commande.localisation_livraison,
            description_colis=commande.numero,
            prix=int(commande.frais_livraison or 0),
        )

        # ── Assignation (fonction commune) ──
        resultat = finaliser_assignation(course)

        # ── Transition commande -> en livraison ──
        commande.statut = Commande.Statut.EN_LIVRAISON
        commande.save(update_fields=['statut'])

        return Response({
            'course': {
                'numero': course.numero,
                'statut': course.statut,
                'prix': course.prix,
            },
            'commande_statut': commande.statut,
            **resultat,
        }, status=201)
