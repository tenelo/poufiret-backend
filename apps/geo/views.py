from rest_framework import generics, permissions

from .models import Departement, Quartier
from .serializers import DepartementSerializer, QuartierSerializer


class DepartementsView(generics.ListAPIView):
    """GET /geo/departements/ — liste des départements pour les dropdowns.

    Public : le choix se fait des l'inscription, avant authentification.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = DepartementSerializer
    pagination_class = None

    def get_queryset(self):
        return (Departement.objects.filter(est_actif=True)
                .select_related('region__district')
                .order_by('region__district__ordre', 'region__ordre',
                          'ordre', 'nom'))


class QuartiersView(generics.ListAPIView):
    """GET /geo/quartiers/?departement=<id> — quartiers actifs d'un
    departement, pour l'autocompletion des points de livraison.
    Public : peut etre consulte avant authentification.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = QuartierSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Quartier.objects.filter(est_actif=True)
        dep = self.request.query_params.get('departement')
        if dep:
            qs = qs.filter(departement_id=dep)
        return qs.order_by('ordre', 'nom')
