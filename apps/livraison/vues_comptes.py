"""Gestion des comptes de la plateforme TeneLivr (livreurs, gestionnaires,
superviseurs), avec droits hiérarchiques cloisonnés par ville.

Hiérarchie (rappel) :
    coordonnateur_livraison  — national, toutes les villes
    superviseur_livraison    — responsable du bureau d'UNE ville
    gestionnaire_livraison   — agent du bureau d'une ville

Matrice de droits :
    - Livreurs      : gestionnaire, superviseur (sa ville), coordonnateur (toutes).
    - Gestionnaires : superviseur (sa ville), coordonnateur (toutes). Pas le gestionnaire.
    - Superviseurs  : coordonnateur uniquement.

Un superviseur/gestionnaire ne peut jamais choisir la ville dans le body :
elle est toujours forcée à la sienne. Seul un coordonnateur (portée
nationale) précise la ville cible.

Regroupé dans apps/livraison/ (comme vues_bureau.py) pour garder le module
TeneLivr isolé et extractible : aucune dépendance vers apps.administration
(pas de journalisation JournalModeration ici, volontairement).
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.validateurs import generer_pin_aleatoire
from apps.geo.models import Departement
from apps.livreurs.models import Livreur
from .models import ProfilLivraison
from .permissions import (EstCoordonnateurLivraison, EstPersonnelLivraison,
                          EstSuperviseurLivraison)

User = get_user_model()


# ── Helpers communs ────────────────────────────────────────────────────

def _est_coordonnateur(user):
    return user.is_superuser or user.role == User.Role.COORDONNATEUR_LIVRAISON


def _ville_acteur(user):
    """Departement (id) de rattachement de l'acteur, ou None (coordonnateur)."""
    profil = getattr(user, 'profil_livraison', None)
    return profil.departement_id if profil else None


def _valider_telephone(telephone):
    """Retourne (telephone_nettoye, erreur). erreur=None si valide."""
    telephone = (telephone or '').strip()
    if not telephone.startswith('+'):
        return telephone, 'Numéro au format international attendu (+225...).'
    if User.objects.filter(telephone=telephone).exists():
        return telephone, 'Un compte existe déjà pour ce numéro.'
    return telephone, None


def _resoudre_ville(request, d):
    """Determine la ville cible d'une creation, selon le niveau de l'acteur.

    Coordonnateur : lit ville_id du body (requis, doit exister).
    Superviseur/gestionnaire : forcee a la ville de l'acteur (ignore le body).

    Retourne (ville_id, erreur). erreur=None si valide.
    """
    if _est_coordonnateur(request.user):
        ville_id = d.get('ville_id')
        if not ville_id:
            return None, 'ville_id requis.'
        if not Departement.objects.filter(pk=ville_id).exists():
            return None, 'Ville (département) introuvable.'
        return ville_id, None
    return _ville_acteur(request.user), None


def _creer_compte_livraison(telephone, prenom, nom, role):
    """Cree le User (PIN aleatoire, pin_par_defaut=True). Retourne (user, pin)."""
    pin = generer_pin_aleatoire()
    user = User(
        telephone=telephone,
        username=telephone,
        first_name=prenom or '',
        last_name=nom or '',
        role=role,
        est_verifie=True,
        pin_par_defaut=True,
    )
    user.set_password(pin)
    user.save()
    return user, pin


# ── Livreurs ────────────────────────────────────────────────────────────

def _livreur_dict(l):
    return {
        'id': str(l.id),
        'telephone': l.user.telephone,
        'nom': l.user.get_full_name() or l.user.username,
        'type_vehicule': l.type_vehicule,
        'statut': l.statut,
        'immatriculation': l.immatriculation,
        'ville_id': l.ville_id,
        'ville_nom': l.ville.nom if l.ville_id else None,
        'compte_actif': l.user.is_active,
    }


class LivreursGestionView(APIView):
    """GET : liste des livreurs (cloisonnée par ville). POST : en créer un."""
    permission_classes = [IsAuthenticated, EstPersonnelLivraison]

    def get(self, request):
        qs = Livreur.objects.select_related('user', 'ville')
        if _est_coordonnateur(request.user):
            ville = request.query_params.get('ville')
            if ville:
                qs = qs.filter(ville_id=ville)
        else:
            qs = qs.filter(ville_id=_ville_acteur(request.user))
        qs = qs.order_by('-cree_le')
        return Response([_livreur_dict(l) for l in qs], status=200)

    def post(self, request):
        d = request.data
        telephone, erreur = _valider_telephone(d.get('telephone'))
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        ville_id, erreur = _resoudre_ville(request, d)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        type_vehicule = d.get('type_vehicule') or Livreur.TypeVehicule.MOTO
        if type_vehicule not in Livreur.TypeVehicule.values:
            return Response(
                {'erreur': True, 'message': 'type_vehicule invalide.'}, status=400)

        with transaction.atomic():
            user, pin = _creer_compte_livraison(
                telephone, d.get('prenom'), d.get('nom'), User.Role.LIVREUR)
            livreur = Livreur.objects.create(
                user=user,
                ville_id=ville_id,
                type_vehicule=type_vehicule,
                immatriculation=d.get('immatriculation', '') or '',
            )

        return Response({
            'livreur_id': str(livreur.id),
            'telephone': user.telephone,
            'pin_clair': pin,
            'message': (f"Livreur créé. Communiquez ce PIN à l'intéressé : "
                       f"{pin}. Il devra le changer à sa première connexion."),
        }, status=201)


class LivreurDetailView(APIView):
    """PATCH : modifier un livreur. DELETE : le désactiver (compte conservé)."""
    permission_classes = [IsAuthenticated, EstPersonnelLivraison]

    def _livreur(self, request, pk):
        qs = Livreur.objects.select_related('user', 'ville').filter(pk=pk)
        if not _est_coordonnateur(request.user):
            qs = qs.filter(ville_id=_ville_acteur(request.user))
        return qs.first()

    def patch(self, request, pk):
        livreur = self._livreur(request, pk)
        if livreur is None:
            return Response({'erreur': True, 'message': 'Livreur introuvable.'},
                            status=404)

        d = request.data
        champs = []
        if 'type_vehicule' in d:
            if d['type_vehicule'] not in Livreur.TypeVehicule.values:
                return Response(
                    {'erreur': True, 'message': 'type_vehicule invalide.'}, status=400)
            livreur.type_vehicule = d['type_vehicule']
            champs.append('type_vehicule')
        if 'immatriculation' in d:
            livreur.immatriculation = d['immatriculation'] or ''
            champs.append('immatriculation')
        if 'statut' in d:
            if d['statut'] not in Livreur.Statut.values:
                return Response(
                    {'erreur': True, 'message': 'statut invalide.'}, status=400)
            livreur.statut = d['statut']
            champs.append('statut')

        if champs:
            livreur.save(update_fields=champs)
        return Response(_livreur_dict(livreur), status=200)

    def delete(self, request, pk):
        livreur = self._livreur(request, pk)
        if livreur is None:
            return Response({'erreur': True, 'message': 'Livreur introuvable.'},
                            status=404)

        with transaction.atomic():
            livreur.statut = Livreur.Statut.HORS_LIGNE
            livreur.save(update_fields=['statut'])
            livreur.user.is_active = False
            livreur.user.save(update_fields=['is_active'])

        return Response({'detail': 'Livreur désactivé.'}, status=200)


# ── Gestionnaires ───────────────────────────────────────────────────────

def _profil_livraison_dict(p):
    return {
        'user_id': p.user_id,
        'telephone': p.user.telephone,
        'nom': p.user.get_full_name() or p.user.username,
        'nom_bureau': p.nom_bureau,
        'ville_id': p.departement_id,
        'ville_nom': p.departement.nom if p.departement_id else None,
        'est_actif': p.est_actif,
        'compte_actif': p.user.is_active,
    }


class GestionnairesView(APIView):
    """GET : liste des gestionnaires (cloisonnée). POST : en créer un.

    Superviseur OU coordonnateur — jamais un gestionnaire lui-même.
    """
    permission_classes = [IsAuthenticated,
                          EstSuperviseurLivraison | EstCoordonnateurLivraison]

    def get(self, request):
        qs = ProfilLivraison.objects.select_related('user', 'departement').filter(
            user__role=User.Role.GESTIONNAIRE_LIVRAISON)
        if _est_coordonnateur(request.user):
            ville = request.query_params.get('ville')
            if ville:
                qs = qs.filter(departement_id=ville)
        else:
            qs = qs.filter(departement_id=_ville_acteur(request.user))
        qs = qs.order_by('-cree_le')
        return Response([_profil_livraison_dict(p) for p in qs], status=200)

    def post(self, request):
        d = request.data
        telephone, erreur = _valider_telephone(d.get('telephone'))
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        ville_id, erreur = _resoudre_ville(request, d)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        with transaction.atomic():
            user, pin = _creer_compte_livraison(
                telephone, d.get('prenom'), d.get('nom'),
                User.Role.GESTIONNAIRE_LIVRAISON)
            profil = ProfilLivraison.objects.create(
                user=user,
                departement_id=ville_id,
                nom_bureau=d.get('nom_bureau', '') or '',
            )

        return Response({
            'gestionnaire_id': user.id,
            'telephone': user.telephone,
            'pin_clair': pin,
            'message': (f"Gestionnaire créé. Communiquez ce PIN à l'intéressé : "
                       f"{pin}. Il devra le changer à sa première connexion."),
        }, status=201)


class GestionnaireDetailView(APIView):
    """DELETE : désactive un gestionnaire (profil_livraison.est_actif=False,
    compte non supprimé)."""
    permission_classes = [IsAuthenticated,
                          EstSuperviseurLivraison | EstCoordonnateurLivraison]

    def delete(self, request, pk):
        qs = ProfilLivraison.objects.select_related('user').filter(
            user_id=pk, user__role=User.Role.GESTIONNAIRE_LIVRAISON)
        if not _est_coordonnateur(request.user):
            qs = qs.filter(departement_id=_ville_acteur(request.user))
        profil = qs.first()
        if profil is None:
            return Response({'erreur': True, 'message': 'Gestionnaire introuvable.'},
                            status=404)

        profil.est_actif = False
        profil.save(update_fields=['est_actif'])
        return Response({'detail': 'Gestionnaire désactivé.'}, status=200)


# ── Superviseurs ────────────────────────────────────────────────────────

class SuperviseursView(APIView):
    """GET : tous les superviseurs. POST : en créer un. Coordonnateur uniquement."""
    permission_classes = [IsAuthenticated, EstCoordonnateurLivraison]

    def get(self, request):
        qs = ProfilLivraison.objects.select_related('user', 'departement').filter(
            user__role=User.Role.SUPERVISEUR_LIVRAISON).order_by('-cree_le')
        return Response([_profil_livraison_dict(p) for p in qs], status=200)

    def post(self, request):
        d = request.data
        telephone, erreur = _valider_telephone(d.get('telephone'))
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        ville_id = d.get('ville_id')
        if not ville_id:
            return Response({'erreur': True, 'message': 'ville_id requis.'}, status=400)
        if not Departement.objects.filter(pk=ville_id).exists():
            return Response(
                {'erreur': True, 'message': 'Ville (département) introuvable.'},
                status=400)

        with transaction.atomic():
            user, pin = _creer_compte_livraison(
                telephone, d.get('prenom'), d.get('nom'),
                User.Role.SUPERVISEUR_LIVRAISON)
            profil = ProfilLivraison.objects.create(
                user=user,
                departement_id=ville_id,
                nom_bureau=d.get('nom_bureau', '') or '',
            )

        return Response({
            'superviseur_id': user.id,
            'telephone': user.telephone,
            'pin_clair': pin,
            'message': (f"Superviseur créé. Communiquez ce PIN à l'intéressé : "
                       f"{pin}. Il devra le changer à sa première connexion."),
        }, status=201)


class SuperviseurDetailView(APIView):
    """DELETE : désactive un superviseur (profil_livraison.est_actif=False,
    compte non supprimé). Coordonnateur uniquement."""
    permission_classes = [IsAuthenticated, EstCoordonnateurLivraison]

    def delete(self, request, pk):
        profil = ProfilLivraison.objects.select_related('user').filter(
            user_id=pk, user__role=User.Role.SUPERVISEUR_LIVRAISON).first()
        if profil is None:
            return Response({'erreur': True, 'message': 'Superviseur introuvable.'},
                            status=404)

        profil.est_actif = False
        profil.save(update_fields=['est_actif'])
        return Response({'detail': 'Superviseur désactivé.'}, status=200)
