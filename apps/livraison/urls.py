"""Routes de l'app livraison (prefixees /api/v1/livraison/)."""
from django.urls import path
from .views import (
    CreerCourseView, MesCoursesView, CourseDetailView, TransitionCourseView,
    CoursesRecuesView, PositionContactView, TarifView, IconesMotardView,
)
from .vues_bureau import (
    CoursesBureauView, LivreursBureauView, AssignerLivreurBureauView,
    CreerCourseBureauView, CoursesCoordonnateurView, LivreursCoordonnateurView,
    AssignerLivreurCoordonnateurView,
)
from .vues_comptes import (
    LivreursGestionView, LivreurDetailView,
    GestionnairesView, GestionnaireDetailView,
    SuperviseursView, SuperviseurDetailView,
)
from .vues_stats import StatsBureauView, StatsCoordonnateurView

urlpatterns = [
    path('tarif/', TarifView.as_view(), name='tarif'),
    path('icones-motard/', IconesMotardView.as_view(), name='icones-motard'),
    path('courses/', MesCoursesView.as_view(), name='courses-liste'),
    path('courses/creer/', CreerCourseView.as_view(), name='course-creer'),
    path('courses/recues/', CoursesRecuesView.as_view(), name='courses-recues'),
    path('courses/<uuid:pk>/', CourseDetailView.as_view(), name='course-detail'),
    path('courses/<uuid:pk>/position-contact/', PositionContactView.as_view(),
         name='course-position-contact'),
    path('courses/<uuid:pk>/transition/', TransitionCourseView.as_view(),
         name='course-transition'),

    # Bureau de gestion (gestionnaire_livraison, cloisonné à son département)
    path('bureau/courses/', CoursesBureauView.as_view(), name='bureau-courses'),
    path('bureau/courses/creer/', CreerCourseBureauView.as_view(),
         name='bureau-course-creer'),
    path('bureau/courses/<uuid:pk>/assigner/', AssignerLivreurBureauView.as_view(),
         name='bureau-course-assigner'),
    path('bureau/livreurs/', LivreursBureauView.as_view(), name='bureau-livreurs'),

    # Comptes TeneLivr (droits hiérarchiques : coordonnateur/superviseur/gestionnaire)
    path('comptes/livreurs/', LivreursGestionView.as_view(), name='comptes-livreurs'),
    path('comptes/livreurs/<uuid:pk>/', LivreurDetailView.as_view(),
         name='comptes-livreur-detail'),
    path('comptes/gestionnaires/', GestionnairesView.as_view(),
         name='comptes-gestionnaires'),
    path('comptes/gestionnaires/<int:pk>/', GestionnaireDetailView.as_view(),
         name='comptes-gestionnaire-detail'),
    path('comptes/superviseurs/', SuperviseursView.as_view(),
         name='comptes-superviseurs'),
    path('comptes/superviseurs/<int:pk>/', SuperviseurDetailView.as_view(),
         name='comptes-superviseur-detail'),

    # Vue nationale coordonnateur (toutes villes, filtre ?ville= optionnel)
    path('coordonnateur/courses/', CoursesCoordonnateurView.as_view(),
         name='coordonnateur-courses'),
    path('coordonnateur/livreurs/', LivreursCoordonnateurView.as_view(),
         name='coordonnateur-livreurs'),
    path('coordonnateur/courses/<uuid:pk>/assigner/',
         AssignerLivreurCoordonnateurView.as_view(),
         name='coordonnateur-course-assigner'),

    # Statistiques
    path('stats/bureau/', StatsBureauView.as_view(), name='stats-bureau'),
    path('stats/coordonnateur/', StatsCoordonnateurView.as_view(),
         name='stats-coordonnateur'),
]
