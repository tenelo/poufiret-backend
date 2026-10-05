"""Vues panier (Module 4 - bloc A1)."""
from datetime import datetime

from django.contrib.gis.geos import Point # type: ignore
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.catalog.models import Article, OptionGroupe, Supplement, Variante
from apps.restaurants import services as services_restaurants
from apps.restaurants.models import LigneMenu
from .models import Panier, LignePanier
from .serializers import PanierSerializer
from apps.notifications.fcm import notifier_utilisateur


def _groupe_options_non_respecte(article, supplements):
    """Premier GroupeOption actif de cet article dont le nombre d'options
    choisies (déduit du snapshot `supplements`, clé groupe_id) ne respecte
    pas min_choix/max_choix — None si tout est en règle. Les articles sans
    GroupeOption (cas général, hors restaurants) ne sont jamais concernés."""
    choix_par_groupe = {}
    for s in supplements or []:
        gid = s.get('groupe_id')
        if gid:
            choix_par_groupe[gid] = choix_par_groupe.get(gid, 0) + 1
    for g in article.groupes_options.filter(est_actif=True):
        n = choix_par_groupe.get(g.id, 0)
        if n < g.min_choix or (g.max_choix is not None and n > g.max_choix):
            return g
    return None


def _snapshot_options_choisies(article, option_ids):
    """Valide et construit le snapshot des options (GroupeOption/
    OptionGroupe, restaurants) choisies pour cet article. Lève ValueError
    (message prêt pour l'API) si un groupe n'a pas son nombre de choix
    requis — ex. garniture (min=max=1) non choisie."""
    options = list(
        OptionGroupe.objects.filter(
            pk__in=option_ids or [], groupe__article=article, est_actif=True,
        ).select_related('groupe'))
    snapshot = [
        {'id': o.id, 'nom': o.nom, 'prix': int(o.prix_supplement),
         'groupe_id': o.groupe_id, 'groupe_libelle': o.groupe.libelle}
        for o in options
    ]
    manquant = _groupe_options_non_respecte(article, snapshot)
    if manquant:
        attendu = (str(manquant.min_choix) if manquant.max_choix == manquant.min_choix
                   else f'{manquant.min_choix} à '
                        f'{manquant.max_choix if manquant.max_choix is not None else "∞"}')
        raise ValueError(f'« {manquant.libelle} » : choisissez {attendu} option(s).')
    return snapshot


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
    """POST /orders/paniers/ajouter/ — ajoute un article (ou une ligne de
    menu restaurant) au panier du bon partenaire.
    Body: article (id) OU ligne_menu (id) — l'un des deux obligatoire ;
    quantite, variante_id? (ignoré pour ligne_menu, prix déjà fixé),
    supplement_ids?[], option_ids?[] (GroupeOption, restaurants : respect
    du min/max de chaque groupe vérifié ici), note_speciale?"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ligne_menu = None
        ligne_menu_id = request.data.get('ligne_menu')
        if ligne_menu_id:
            ligne_menu = get_object_or_404(
                LigneMenu.objects.select_related('menu__restaurant__partenaire', 'plat'),
                pk=ligne_menu_id)
            article = ligne_menu.plat
            prix = ligne_menu.prix_effectif
            variante_id = None
        else:
            article = get_object_or_404(Article, pk=request.data.get('article'), est_actif=True)
            prix = article.prix_promotion if (article.est_en_promotion and article.prix_promotion) else article.prix
            prix = prix or 0
            variante_id = request.data.get('variante_id')
            if variante_id:
                v = Variante.objects.filter(pk=variante_id, article=article).first()
                if v:
                    prix += v.prix_supplement

        quantite = int(request.data.get('quantite', 1))
        if quantite < 1:
            return Response({'erreur': True, 'message': 'Quantité invalide.'}, status=400)

        # Panier pur (partenaire + catégorie de cet article), créé si absent
        panier, _ = Panier.objects.get_or_create(
            user=request.user,
            partenaire=article.partenaire,
            categorie=article.categorie,
        )

        # Snapshot des suppléments (legacy) + options de groupes (restaurants)
        supp_ids = request.data.get('supplement_ids', []) or []
        supplements = [
            {'id': s.id, 'nom': s.nom, 'prix': int(s.prix)}
            for s in Supplement.objects.filter(pk__in=supp_ids, article=article)
        ]
        try:
            supplements += _snapshot_options_choisies(article, request.data.get('option_ids'))
        except ValueError as e:
            return Response({'erreur': True, 'message': str(e)}, status=400)

        ligne = LignePanier.objects.create(
            panier=panier, article=article, variante_id=variante_id or None,
            ligne_menu=ligne_menu,
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
from .models import Commande, LigneCommande, HistoriqueCommande
from .serializers import CommandeSerializer
from .services import (
    TRANSITIONS, DemandeLivreurInvalide, LivraisonEnCoursError,
    _notifier_admins_commande, appliquer_transition_commande, demander_livreur,
)


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
        lignes = list(panier.lignes.select_related('article', 'ligne_menu__menu__restaurant'))
        if not lignes:
            return Response({'erreur': True, 'message': 'Panier vide.'}, status=400)

        # ── Validations restaurant (ouverture, délai limite, groupes d'options) ──
        for l in lignes:
            if l.ligne_menu_id:
                restaurant = l.ligne_menu.menu.restaurant
                if not services_restaurants.est_ouvert(restaurant):
                    return Response(
                        {'erreur': True, 'message': services_restaurants.message_statut(restaurant)},
                        status=400)
                if not services_restaurants.menu_commandable(l.ligne_menu.menu):
                    return Response(
                        {'erreur': True,
                         'message': 'Heure limite de commande dépassée pour ce menu.'},
                        status=400)
            manquant = _groupe_options_non_respecte(l.article, l.supplements)
            if manquant:
                return Response(
                    {'erreur': True,
                     'message': f'« {manquant.libelle} » : choix invalide.'}, status=400)

        # ── Décrément du stock journalier (menus), verrouillé, avant toute
        # création — en cas d'échec, annule tout le reste de la validation. ──
        try:
            for l in lignes:
                if l.ligne_menu_id:
                    services_restaurants.decrementer_stock(
                        l.ligne_menu, l.quantite, pour_date=timezone.localdate())
        except services_restaurants.StockInsuffisantError as e:
            transaction.set_rollback(True)
            return Response({'erreur': True, 'message': str(e)}, status=400)

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
                note_speciale=l.note_speciale, ligne_menu=l.ligne_menu,
            )
        panier.delete()  # vide le panier

        # Notifie le partenaire une fois la commande réellement persistée
        # (après commit, pour ne jamais notifier une commande qui serait
        # finalement annulée par un rollback plus loin dans ce bloc atomic).
        transaction.on_commit(lambda: notifier_utilisateur(
            commande.partenaire.user,
            request.user.get_full_name() or 'Nouvelle commande',
            f'Nouvelle commande {commande.numero} reçue.',
            data={
                'type': 'commande',
                'commande_id': str(commande.id),
                'statut': str(commande.statut),
            },
            request=request,
        ))
        # Notification admin (centre de gestion) — même point central que
        # la notification partenaire ci-dessus, après commit également.
        transaction.on_commit(lambda: _notifier_admins_commande(
            commande, 'commande_nouvelle', 'Nouvelle commande',
            f'{commande.numero} — {request.user.get_full_name() or request.user.telephone} '
            f'→ {commande.partenaire.nom_commerce} ({int(commande.total)} FCFA)',
        ))

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


class TransitionCommandeView(APIView):
    """POST /orders/commandes/<id>/transition/ — change le statut selon le workflow.
    Body: statut (cible), raison_refus? Le partenaire gère accept/refus/prepa/prete/livraison;
    le client peut annuler une commande encore 'nouvelle'.

    Délègue à services.appliquer_transition_commande (source unique,
    partagée avec le centre de gestion admin) pour l'application du
    changement, l'historisation et les notifications — logique de garde
    d'accès et ordre des vérifications inchangés."""
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
            role = HistoriqueCommande.ActeurRole.CLIENT
        else:
            role = HistoriqueCommande.ActeurRole.PARTENAIRE

        ok, message = appliquer_transition_commande(
            c, cible, u, role,
            commentaire=request.data.get('raison_refus', ''), request=request)
        if not ok:
            return Response({'erreur': True, 'message': message}, status=400)
        return Response(CommandeSerializer(c, context={'request': request}).data)


class CommanderLivreurView(APIView):
    """POST /orders/commandes/<pk>/livreur/ — le partenaire proprietaire
    declenche une course de livraison pour une commande prete.

    Délègue à services.demander_livreur (source unique, partagée avec le
    centre de gestion admin) — mêmes gardes, même ordre, même comportement."""
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk=None):
        commande = get_object_or_404(Commande, pk=pk)

        profil = getattr(request.user, 'profil_partenaire', None)
        if profil is None or commande.partenaire_id != profil.pk:
            return Response(
                {'erreur': True, 'message': "Vous n'etes pas le partenaire de cette commande."},
                status=403)

        try:
            course, resultat = demander_livreur(commande, request.user, type_demandeur='partenaire')
        except LivraisonEnCoursError as exc:
            return Response(
                {'erreur': True, 'message': str(exc), 'course_numero': exc.numero_course},
                status=409)
        except DemandeLivreurInvalide as exc:
            return Response({'erreur': True, 'message': str(exc)}, status=400)

        return Response({
            'course': {
                'numero': course.numero,
                'statut': course.statut,
                'prix': course.prix,
            },
            'commande_statut': commande.statut,
            **resultat,
        }, status=201)
