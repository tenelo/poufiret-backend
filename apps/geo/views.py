from rest_framework import generics, permissions

from .models import Departement
from .serializers import DepartementSerializer


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
