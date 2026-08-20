"""Vues du bureau de gestion de livraison (rôle gestionnaire_livraison).

Chaque gestionnaire est rattaché à un département (sa ville) via son
profil_livraison, et ne voit/agit QUE sur les courses et livreurs de ce
département. Réutilise les mêmes briques que les vues « grand public »
(apps.livraison.views) : `_course_dict`, `finaliser_assignation`,
`notifier_transition` — aucune de ces briques n'est modifiée ici.

Regroupé dans apps/livraison/ (et pas dans une app transverse) pour garder
le module TeneLivr isolé et extractible, cohérent avec ProfilLivraison et
apps.livraison.permissions.
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.livreurs.models import Livreur
from .destinataire import programmer_lookup_destinataire
from .models import Course
from .notifications_course import notifier_transition
from .permissions import EstCoordonnateurLivraison, EstGestionnaireLivraison
from .views import _course_dict, _numero, _point, finaliser_assignation

# Statuts depuis lesquels une assignation manuelle (initiale ou
# réassignation) est autorisée. Une fois acceptée par le livreur ou plus
# avancée, seul le cycle normal du livreur/demandeur peut faire évoluer
# la course (voir TransitionCourseView).
STATUTS_ASSIGNABLES = {
    Course.Statut.DEMANDEE, Course.Statut.ASSIGNEE, Course.Statut.REFUSEE,
}


def _parser_ville(request):
    """Lit ?ville=<id departement>, commun aux endpoints coordonnateur.

    Absent -> (None, None) : « toutes les villes ». Format non entier ->
    (None, message d'erreur) pour un 400 propre — jamais de 500. Un id
    numérique mais inexistant n'est PAS une erreur ici : le filtre ne
    remontera simplement aucun résultat (liste/stats à zéro), cohérent
    avec la consigne de ne jamais planter sur un id invalide.
    """
    brut = request.query_params.get('ville')
    if not brut:
        return None, None
    try:
        return int(brut), None
    except (TypeError, ValueError):
        return None, 'Paramètre ville invalide (id numérique de département attendu).'


def _livreur_bureau_dict(l):
    """Représentation d'un livreur pour les écrans bureau/coordonnateur."""
    pos = l.position
    return {
        'id': str(l.id),
        'nom': l.user.get_full_name() or l.user.username,
        'telephone': l.user.telephone,
        'type_vehicule': l.type_vehicule,
        'statut': l.statut,
        'ville_id': l.ville_id,
        'latitude': pos.y if pos else None,
        'longitude': pos.x if pos else None,
        'position_maj_le': (
            l.position_maj_le.isoformat() if l.position_maj_le else None
        ),
    }


class CoursesBureauView(APIView):
    """GET /livraison/bureau/courses/ — courses du département du bureau."""
    permission_classes = [IsAuthenticated, EstGestionnaireLivraison]

    def get(self, request):
        profil = request.user.profil_livraison
        qs = Course.objects.filter(
            ville_id=profil.departement_id).order_by('-cree_le')
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        return Response([_course_dict(c) for c in qs[:100]], status=200)


class LivreursBureauView(APIView):
    """GET /livraison/bureau/livreurs/ — livreurs du département du bureau."""
    permission_classes = [IsAuthenticated, EstGestionnaireLivraison]

    def get(self, request):
        profil = request.user.profil_livraison
        qs = Livreur.objects.filter(
            ville_id=profil.departement_id).select_related('user')
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        return Response([_livreur_bureau_dict(l) for l in qs], status=200)


class AssignerLivreurBureauView(APIView):
    """POST /livraison/bureau/courses/<pk>/assigner/ — assignation manuelle.

    Body : {"livreur_id": "..."}. Même mécanisme de pose des champs que
    l'assignation automatique (finaliser_assignation) : livreur, statut
    ASSIGNEE, assignee_le, puis notifier_transition — pour que le livreur
    et les écrans de suivi ne voient aucune différence entre une
    assignation auto et une assignation manuelle du bureau.
    """
    permission_classes = [IsAuthenticated, EstGestionnaireLivraison]

    def post(self, request, pk=None):
        profil = request.user.profil_livraison

        course = Course.objects.filter(
            pk=pk, ville_id=profil.departement_id).first()
        if course is None:
            return Response({'erreur': True, 'message': 'Course introuvable.'},
                            status=404)

        livreur_id = request.data.get('livreur_id')
        livreur = None
        if livreur_id:
            livreur = Livreur.objects.filter(
                pk=livreur_id, ville_id=profil.departement_id).first()
        if livreur is None:
            return Response(
                {'erreur': True,
                 'message': 'Livreur introuvable ou hors de votre département.'},
                status=400)

        if course.statut not in STATUTS_ASSIGNABLES:
            return Response(
                {'erreur': True,
                 'message': ('Impossible d\'assigner un livreur : course au '
                            f'statut "{course.get_statut_display()}".')},
                status=400)

        course.livreur = livreur
        course.statut = Course.Statut.ASSIGNEE
        course.assignee_le = timezone.now()
        course.save(update_fields=['livreur', 'statut', 'assignee_le'])
        notifier_transition(course, 'assignee')
        return Response(_course_dict(course), status=200)


class CreerCourseBureauView(APIView):
    """POST /livraison/bureau/courses/creer/ — crée une course au nom du bureau.

    Mêmes champs requis que CreerCourseView (apps.livraison.views), mais la
    ville n'est jamais lue du body : elle est forcée au département du
    gestionnaire connecté — un bureau ne crée que dans sa propre ville.
    """
    permission_classes = [IsAuthenticated, EstGestionnaireLivraison]

    def post(self, request):
        profil = request.user.profil_livraison
        d = request.data
        requis = ['a_quartier', 'a_nom_contact', 'a_telephone_contact',
                  'b_quartier', 'b_nom_contact', 'b_telephone_contact']
        manquants = [k for k in requis if not d.get(k)]
        if manquants:
            return Response({'erreur': True,
                             'message': f"Champs requis: {', '.join(manquants)}."},
                            status=400)

        course = Course.objects.create(
            numero=_numero(),
            demandeur=request.user,
            type_demandeur='bureau',
            ville_id=profil.departement_id,
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

        programmer_lookup_destinataire(course)

        resultat = finaliser_assignation(course)
        return Response({'course': _course_dict(course), **resultat}, status=201)


class CoursesCoordonnateurView(APIView):
    """GET /livraison/coordonnateur/courses/ — toutes les villes.

    Équivalent de CoursesBureauView mais sans cloisonnement : le
    coordonnateur voit toutes les courses, avec un filtre ?ville=<id>
    optionnel (même paramètre/sémantique que les autres endpoints
    coordonnateur — voir _parser_ville).
    """
    permission_classes = [IsAuthenticated, EstCoordonnateurLivraison]

    def get(self, request):
        ville_id, erreur = _parser_ville(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        qs = Course.objects.all()
        if ville_id is not None:
            qs = qs.filter(ville_id=ville_id)
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        qs = qs.order_by('-cree_le')
        return Response([_course_dict(c) for c in qs[:100]], status=200)


class LivreursCoordonnateurView(APIView):
    """GET /livraison/coordonnateur/livreurs/ — toutes les villes.

    Équivalent de LivreursBureauView mais sans cloisonnement, avec le même
    filtre ?ville=<id> optionnel que les autres endpoints coordonnateur.
    """
    permission_classes = [IsAuthenticated, EstCoordonnateurLivraison]

    def get(self, request):
        ville_id, erreur = _parser_ville(request)
        if erreur:
            return Response({'erreur': True, 'message': erreur}, status=400)

        qs = Livreur.objects.select_related('user')
        if ville_id is not None:
            qs = qs.filter(ville_id=ville_id)
        s = request.query_params.get('statut')
        if s:
            qs = qs.filter(statut=s)
        return Response([_livreur_bureau_dict(l) for l in qs], status=200)
