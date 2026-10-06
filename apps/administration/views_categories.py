"""CRUD admin des catégories (menu « Catégories »). Capacité gerer_parametres.
Ordre et visibilité restent dans views_parametres (réutilisés, non dupliqués).
"""
from django.db import transaction
from django.db.models import Count, F, Max
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Categorie
from apps.catalog.recherche import normaliser_mots_cles
from apps.core.permissions import ADroitDe
from apps.users.models import ProfilPartenaire

from .moderation import _journaliser
from .models import JournalModeration

_PERMISSION = [IsAuthenticated, ADroitDe('gerer_parametres')]
TYPES = ProfilPartenaire.TypePartenaire


def _erreurs_unicite(inst, nom, parent, types):
    """Nom unique parmi les non archivées du même niveau (insensible à la casse),
    et chaque type déclaré sur une seule catégorie non archivée. None si OK."""
    freres = Categorie.objects.filter(est_archivee=False, parent=parent, nom__iexact=nom)
    if inst is not None:
        freres = freres.exclude(pk=inst.pk)
    if freres.exists():
        return {'nom': [f'Une catégorie « {nom} » existe déjà à ce niveau.']}
    libelles = dict(TYPES.choices)
    for t in types or []:
        autre = Categorie.objects.filter(est_archivee=False, types_partenaire__contains=[t])
        if inst is not None:
            autre = autre.exclude(pk=inst.pk)
        autre = autre.first()
        if autre is not None:
            return {'types_partenaire': [
                f'Le type « {libelles[t]} » est déjà déclaré sur la catégorie « {autre.nom} ».']}
    return None


def _slug_unique(nom):
    base = slugify(nom)[:110] or 'categorie'
    slug, n = base, 1
    while Categorie.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


def _ordre_suivant(parent):
    niveau = Categorie.objects.filter(est_archivee=False, parent=parent)
    return (niveau.aggregate(m=Max('ordre'))['m'] or 0) + 1


class CategorieAdminSerializer(serializers.ModelSerializer):
    nom = serializers.CharField(max_length=100)
    image = serializers.ImageField(source='image_couverture', required=False, allow_null=True)
    supprimer_image = serializers.BooleanField(write_only=True, required=False)
    parent_id = serializers.PrimaryKeyRelatedField(
        source='parent', queryset=Categorie.objects.filter(est_archivee=False),
        required=False, allow_null=True)
    parent_nom = serializers.CharField(source='parent.nom', read_only=True, default=None)
    types_partenaire = serializers.ListField(
        child=serializers.ChoiceField(choices=TYPES.choices), required=False)
    mots_cles = serializers.ListField(child=serializers.CharField(max_length=200), required=False)
    nb_partenaires = serializers.SerializerMethodField()
    nb_enfants = serializers.SerializerMethodField()

    class Meta:
        model = Categorie
        fields = ['id', 'nom', 'slug', 'description', 'icone', 'image', 'supprimer_image', 'ordre',
                  'est_active', 'est_archivee', 'parent_id', 'parent_nom', 'types_partenaire',
                  'mots_cles', 'nb_partenaires', 'nb_enfants']
        read_only_fields = ['slug', 'ordre', 'est_archivee']
        extra_kwargs = {'description': {'required': False, 'allow_blank': True},
                        'icone': {'required': False, 'allow_blank': True, 'max_length': 50}}

    def get_nb_partenaires(self, obj):
        n = getattr(obj, '_nb_partenaires', None)
        return n if n is not None else obj.liens_partenaires.count()

    def get_nb_enfants(self, obj):
        n = getattr(obj, '_nb_enfants', None)
        return n if n is not None else obj.enfants.count()

    def validate_mots_cles(self, valeur):
        mots = normaliser_mots_cles(valeur)
        if mots is None:
            raise serializers.ValidationError('Liste de textes attendue (100 mots max, 60 caractères chacun).')
        return mots

    def validate_types_partenaire(self, valeur):
        return list(dict.fromkeys(valeur))

    def validate(self, attrs):
        inst = self.instance
        parent = attrs['parent'] if 'parent' in attrs else (inst.parent if inst else None)
        if inst is not None and parent is not None:
            if parent.pk == inst.pk:
                raise serializers.ValidationError({'parent_id': ['Une catégorie ne peut pas être son propre parent.']})
            ancetre = parent.parent
            while ancetre is not None:
                if ancetre.pk == inst.pk:
                    raise serializers.ValidationError(
                        {'parent_id': ['Ce parent est une sous-catégorie de cette catégorie (cycle).']})
                ancetre = ancetre.parent
        nom = attrs.get('nom', inst.nom if inst else None)
        types = attrs.get('types_partenaire', inst.types_partenaire if inst else [])
        erreurs = _erreurs_unicite(inst, nom, parent, types)
        if erreurs:
            raise serializers.ValidationError(erreurs)
        return attrs

    def create(self, validated_data):
        validated_data.pop('supprimer_image', None)
        validated_data['slug'] = _slug_unique(validated_data['nom'])
        validated_data['ordre'] = _ordre_suivant(validated_data.get('parent'))
        return super().create(validated_data)

    def update(self, inst, validated_data):
        supprimer = validated_data.pop('supprimer_image', False)
        if supprimer and 'image_couverture' not in validated_data:
            if inst.image_couverture:
                inst.image_couverture.delete(save=False)
            validated_data['image_couverture'] = None
        if 'parent' in validated_data and validated_data['parent'] != inst.parent:
            validated_data['ordre'] = _ordre_suivant(validated_data['parent'])
        return super().update(inst, validated_data)


def _categorie_ou_404(pk):
    return Categorie.objects.filter(pk=pk).first()


def _nb_partenaires_et_enfants(qs):
    return qs.annotate(_nb_partenaires=Count('liens_partenaires', distinct=True),
                       _nb_enfants=Count('enfants', distinct=True))


class CategoriesAdminListCreateView(APIView):
    """GET ?archivees=0|1 — liste (archivées exclues par défaut, incluses avec 1).
    POST — crée une catégorie (JSON ou multipart)."""
    permission_classes = _PERMISSION

    def get(self, request):
        archivees = request.query_params.get('archivees', '0')
        if archivees not in ('0', '1'):
            return Response({'erreur': True, 'details': {'archivees': ['Valeur attendue : 0 ou 1.']}}, status=400)
        qs = Categorie.objects.all()
        if archivees == '0':
            qs = qs.filter(est_archivee=False)
        qs = _nb_partenaires_et_enfants(qs).order_by(F('parent_id').asc(nulls_first=True), 'ordre', 'nom')
        ser = CategorieAdminSerializer(qs, many=True, context={'request': request})
        return Response({'resultats': ser.data})

    def post(self, request):
        ser = CategorieAdminSerializer(data=request.data, context={'request': request})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        with transaction.atomic():
            obj = ser.save()
            _journaliser(request.user, None, JournalModeration.Action.CAT_CREATION,
                         f'« {obj.nom} » créée (parent={obj.parent_id})')
        return Response(CategorieAdminSerializer(obj, context={'request': request}).data, status=201)


class CategorieAdminDetailView(APIView):
    """PATCH <id>/ (partiel, supprimer_image=true) ; DELETE <id>/ (204 ou 409)."""
    permission_classes = _PERMISSION

    def patch(self, request, pk):
        inst = _categorie_ou_404(pk)
        if inst is None:
            return Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        ser = CategorieAdminSerializer(inst, data=request.data, partial=True, context={'request': request})
        if not ser.is_valid():
            return Response({'erreur': True, 'details': ser.errors}, status=400)
        with transaction.atomic():
            obj = ser.save()
            modifies = sorted(k for k in request.data.keys() if k != 'supprimer_image')
            _journaliser(request.user, None, JournalModeration.Action.CAT_MODIFICATION,
                         f'« {obj.nom} » modifiée : {", ".join(modifies)}'[:255])
        return Response(CategorieAdminSerializer(obj, context={'request': request}).data)

    def delete(self, request, pk):
        inst = _categorie_ou_404(pk)
        if inst is None:
            return Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        nb_p = inst.liens_partenaires.count()
        nb_a = inst.articles.count()
        nb_e = inst.enfants.count()
        if nb_p or nb_a or nb_e:
            return Response({'erreur': True, 'message':
                             f'Impossible de supprimer : {nb_p} partenaire(s) / {nb_a} article(s) / '
                             f'{nb_e} sous-catégorie(s) y sont rattachés. Archivez-la à la place.'}, status=409)
        with transaction.atomic():
            nom = inst.nom
            inst.delete()
            _journaliser(request.user, None, JournalModeration.Action.CAT_SUPPRESSION, f'« {nom} » supprimée')
        return Response(status=204)


class CategorieArchiverView(APIView):
    """POST <id>/archiver/ {"archivee": bool}. Désarchiver revérifie l'unicité."""
    permission_classes = _PERMISSION

    def post(self, request, pk):
        inst = _categorie_ou_404(pk)
        if inst is None:
            return Response({'erreur': True, 'message': 'Catégorie introuvable.'}, status=404)
        archivee = request.data.get('archivee')
        if not isinstance(archivee, bool):
            return Response({'erreur': True, 'details': {'archivee': ['Booléen attendu.']}}, status=400)
        if archivee == inst.est_archivee:
            return Response(CategorieAdminSerializer(inst, context={'request': request}).data)
        if not archivee:
            erreurs = _erreurs_unicite(inst, inst.nom, inst.parent, inst.types_partenaire)
            if erreurs:
                return Response({'erreur': True, 'details': erreurs}, status=400)
        with transaction.atomic():
            inst.est_archivee = archivee
            inst.save(update_fields=['est_archivee'])
            action = JournalModeration.Action.CAT_ARCHIVAGE if archivee else JournalModeration.Action.CAT_DESARCHIVAGE
            _journaliser(request.user, None, action, f'« {inst.nom} » {"archivée" if archivee else "désarchivée"}')
        return Response(CategorieAdminSerializer(inst, context={'request': request}).data)


class TypesPartenaireCategoriesView(APIView):
    """GET types-partenaire/ — les 16 types, avec la catégorie qui les déclare (null sinon)."""
    permission_classes = _PERMISSION

    def get(self, request):
        resultats = []
        for valeur, libelle in TYPES.choices:
            cat = Categorie.objects.filter(est_archivee=False, types_partenaire__contains=[valeur]).order_by('id').first()
            resultats.append({'valeur': valeur, 'libelle': libelle,
                              'categorie_id': cat.id if cat else None,
                              'categorie_nom': cat.nom if cat else None})
        return Response({'resultats': resultats})
