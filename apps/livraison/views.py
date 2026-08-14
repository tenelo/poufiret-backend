"""Vues de l'app livraison : creer/lister/transitions de course +
assignation automatique au livreur le plus proche.
"""
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.livreurs.models import Livreur
from .models import (Course, ParametresLivraison, TRANSITIONS,
                     ANNULATION_DEMANDEUR_JUSQUA)
from .destinataire import programmer_lookup_destinataire
from .notifications_course import notifier_transition


def _numero():
    """Numero LIV-ANNEE-00001, incremental par annee."""
    annee = timezone.now().year
    n = Course.objects.filter(numero__startswith=f'LIV-{annee}-').count() + 1
    return f'LIV-{annee}-{n:05d}'


def _point(lat, lng):
    if lat is None or lng is None:
        return None
    return Point(float(lng), float(lat), srid=4326)


def _course_dict(c):
    def pt(p):
        return {'latitude': p.y, 'longitude': p.x} if p else None
    return {
        'id': str(c.id),
        'numero': c.numero,
        'statut': c.statut,
        'ville': c.ville.nom if c.ville_id else '',
        'description_colis': c.description_colis,
        'prix': c.prix,
        'point_a': {
            'quartier': c.a_quartier,
            'nom_contact': c.a_nom_contact,
            'telephone_contact': c.a_telephone_contact,
            'gps': pt(c.a_position),
        },
        'point_b': {
            'quartier': c.b_quartier,
            'nom_contact': c.b_nom_contact,
            'telephone_contact': c.b_telephone_contact,
            'gps': pt(c.b_position),
        },
        'livreur': str(c.livreur_id) if c.livreur_id else None,
        'livreur_position': _livreur_position(c),
        'cree_le': c.cree_le.isoformat(),
    }


def _livreur_position(c):
    """Derniere position connue du livreur assigne (ou None)."""
    liv = c.livreur
    if liv is None or liv.position is None:
        return None
    return {
        'latitude': liv.position.y,
        'longitude': liv.position.x,
        'type_vehicule': liv.type_vehicule,
        'maj_le': liv.position_maj_le.isoformat() if liv.position_maj_le else None,
    }


def _assigner_plus_proche(course):
    """Choisit le livreur EN LIGNE le plus proche du point A (ou de la ville).
    Vol d'oiseau (PostGIS). Retourne le livreur ou None. Departage aleatoire
    naturel via l'ordre de la base quand distances egales."""
    qs = Livreur.objects.filter(
        statut=Livreur.Statut.EN_LIGNE,
        ville_id=course.ville_id,
        position__isnull=False,
    )
    ref = course.a_position
    if ref is not None:
        qs = qs.annotate(distance=Distance('position', ref)).order_by('distance', '?')
    else:
        qs = qs.order_by('?')
    return qs.first()


class TarifView(APIView):
    """GET /livraison/tarif/ — prix de course courant (public, lecture seule).
    Pilotable depuis l'admin ; le formulaire le lit au chargement."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        p = ParametresLivraison.obtenir()
        return Response({'prix_course': p.prix_course}, status=200)


class CreerCourseView(APIView):
    """POST /livraison/courses/ — cree une course directe A -> B et tente
    l'assignation automatique au livreur le plus proche."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        requis = ['ville', 'a_quartier', 'a_nom_contact', 'a_telephone_contact',
                  'b_quartier', 'b_nom_contact', 'b_telephone_contact']
        manquants = [k for k in requis if not d.get(k)]
        if manquants:
            return Response({'erreur': True,
                             'message': f"Champs requis: {', '.join(manquants)}."},
                            status=400)

        type_dem = 'partenaire' if hasattr(request.user, 'profil_partenaire') else 'client'
        course = Course.objects.create(
            numero=_numero(),
            demandeur=request.user,
            type_demandeur=type_dem,
            ville_id=d['ville'],
            a_quartier=d['a_quartier'],
            a_nom_contact=d['a_nom_contact'],
            a_telephone_contact=d['a_telephone_contact'],
            a_position=_point(d.get('a_latitude'), d.get('a_longitude')),
            b_quartier=d['b_quartier'],
            b_nom_contact=d['b_nom_contact'],
            b_telephone_contact=d['b_telephone_contact'],
            b_position=_point(d.get('b_latitude'), d.get('b_longitude')),
            description_colis=d.get('description_colis', ''),
            prix=int(d.get('prix') or 0),
        )

        # Lookup destinataire : async, non-bloquant, apres commit.
        # Couvre les deux sorties (assigne ou non). Silencieux cote demandeur.
        programmer_lookup_destinataire(course)

        livreur = _assigner_plus_proche(course)
        if livreur is None:
            return Response({
                'course': _course_dict(course),
                'message': "Aucun livreur disponible pour l'instant. Reessayez bientot.",
                'assigne': False,
            }, status=201)

        course.livreur = livreur
        course.statut = Course.Statut.ASSIGNEE
        course.assignee_le = timezone.now()
        course.save(update_fields=['livreur', 'statut', 'assignee_le'])
        notifier_transition(course, 'assignee')
        return Response({
            'course': _course_dict(course),
            'assigne': True,
        }, status=201)


class MesCoursesView(APIView):
    """GET /livraison/courses/ — historique des courses du demandeur."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Course.objects.filter(demandeur=request.user)
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        return Response([_course_dict(c) for c in qs[:100]], status=200)


class CourseDetailView(APIView):
    """GET /livraison/courses/<id>/ — detail d'une course (demandeur ou livreur)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        c = get_object_or_404(Course, pk=pk)
        est_demandeur = c.demandeur_id == request.user.id
        livreur = getattr(request.user, 'profil_livreur', None)
        est_livreur = livreur is not None and c.livreur_id == livreur.id
        est_destinataire = c.contact_user_id == request.user.id
        if not (est_demandeur or est_livreur or est_destinataire):
            return Response({'erreur': True, 'message': 'Acces refuse.'}, status=403)
        return Response(_course_dict(c), status=200)


class CoursesRecuesView(APIView):
    """GET /livraison/courses/recues/ — courses ou je suis le destinataire
    (contact_user). Alimente la surface 'colis qui m'arrivent'."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Course.objects.filter(contact_user=request.user)
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        return Response([_course_dict(c) for c in qs[:100]], status=200)


class PositionContactView(APIView):
    """POST /livraison/courses/<id>/position-contact/ — le destinataire
    depose sa position GPS reelle sur SON point (B). Il ne pilote pas la
    course : il ne peut ni transitionner ni annuler. Ses coords ecrasent
    la saisie manuelle du point B."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        c = get_object_or_404(Course, pk=pk)
        if c.contact_user_id != request.user.id:
            return Response({'erreur': True, 'message': 'Acces refuse.'}, status=403)
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        pt = _point(lat, lng)
        if pt is None:
            return Response({'erreur': True,
                             'message': 'latitude et longitude requises.'}, status=400)
        c.b_position = pt
        c.save(update_fields=['b_position'])
        return Response(_course_dict(c), status=200)


class TransitionCourseView(APIView):
    """POST /livraison/courses/<id>/transition/ — change le statut.
    Body: statut (cible), raison_refus?. Le livreur mene le cycle
    (accepte -> vers_a -> colis_pris -> vers_b -> livree). Le demandeur
    peut annuler tant que le colis n'est pas pris."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk=None):
        c = get_object_or_404(Course, pk=pk)
        cible = request.data.get('statut')
        livreur = getattr(request.user, 'profil_livreur', None)
        est_demandeur = c.demandeur_id == request.user.id
        est_livreur = livreur is not None and c.livreur_id == livreur.id

        if not (est_demandeur or est_livreur):
            return Response({'erreur': True, 'message': 'Acces refuse.'}, status=403)
        if cible not in TRANSITIONS.get(c.statut, []):
            return Response({'erreur': True,
                             'message': f'Transition {c.statut} -> {cible} non autorisee.'},
                            status=400)

        # Le demandeur ne peut qu'annuler, et seulement avant colis pris.
        if est_demandeur and not est_livreur:
            if cible != 'annulee' or c.statut not in ANNULATION_DEMANDEUR_JUSQUA:
                return Response({'erreur': True,
                                 'message': "En tant que demandeur, vous ne pouvez qu'annuler avant recuperation du colis."},
                                status=403)

        now = timezone.now()
        c.statut = cible
        if cible == 'acceptee':
            c.acceptee_le = now
        elif cible == 'colis_pris':
            c.colis_pris_le = now
        elif cible == 'livree':
            c.livree_le = now
        elif cible == 'annulee':
            c.annulee_le = now
        elif cible == 'refusee':
            c.raison_refus = request.data.get('raison_refus', '')
        c.save()
        notifier_transition(c, cible)
        return Response(_course_dict(c), status=200)
