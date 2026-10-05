from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Departement, Localite, Quartier
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
    """GET /geo/quartiers/?departement=<id> — liste brute (inchangée).
    GET /geo/quartiers/?localite=<id> — {"resultats": [{id, nom}]} pour les
    cascades de saisie. Public : peut etre consulte avant authentification.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = QuartierSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        localite = request.query_params.get('localite')
        if localite is None:
            return super().list(request, *args, **kwargs)
        if not localite.isdigit():
            return Response({'resultats': []})
        qs = (Quartier.objects.filter(est_actif=True, localite_id=localite)
              .order_by('nom').values('id', 'nom'))
        return Response({'resultats': list(qs)})

    def get_queryset(self):
        qs = Quartier.objects.filter(est_actif=True)
        dep = self.request.query_params.get('departement')
        if dep:
            # Quartier est desormais rattache a une Localite (elle-meme
            # rattachee au departement) — contrat de l'URL inchange, seul
            # le chemin ORM change (voir apps.geo.models.Localite).
            qs = qs.filter(localite__departement_id=dep)
        return qs.order_by('ordre', 'nom')


class LocalitesView(APIView):
    """GET /geo/localites/?departement=<id> — {"resultats": [{id, nom}]}.
    Actives, triées par nom. Public."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = Localite.objects.filter(est_actif=True)
        dep = request.query_params.get('departement')
        if dep:
            if not dep.isdigit():
                return Response({'resultats': []})
            qs = qs.filter(departement_id=dep)
        return Response({'resultats': list(qs.order_by('nom').values('id', 'nom'))})
