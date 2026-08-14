"""Routes de l'app livraison (prefixees /api/v1/livraison/)."""
from django.urls import path
from .views import (
    CreerCourseView, MesCoursesView, CourseDetailView, TransitionCourseView,
    CoursesRecuesView, PositionContactView, TarifView,
)

urlpatterns = [
    path('tarif/', TarifView.as_view(), name='tarif'),
    path('courses/', MesCoursesView.as_view(), name='courses-liste'),
    path('courses/creer/', CreerCourseView.as_view(), name='course-creer'),
    path('courses/recues/', CoursesRecuesView.as_view(), name='courses-recues'),
    path('courses/<uuid:pk>/', CourseDetailView.as_view(), name='course-detail'),
    path('courses/<uuid:pk>/position-contact/', PositionContactView.as_view(),
         name='course-position-contact'),
    path('courses/<uuid:pk>/transition/', TransitionCourseView.as_view(),
         name='course-transition'),
]
