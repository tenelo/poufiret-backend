"""Serializers admin (CRUD complet) des formules pub et des paramètres
généraux de diffusion.

Distincts des serializers publics (apps.publicites.serializers, INCHANGÉS) :
ceux-ci exposent tous les champs des modèles pour l'édition admin, plus des
compteurs en lecture seule (nb_actives, nb_en_attente, nb_pubs_total).
Réservés à ADroitDe('gerer_formules_pub') — voir apps.publicites.views_admin.
"""
from rest_framework import serializers

from .models import FormulePublicite, ParametresPublicite, TypeAffichage


class FormulePubliciteAdminSerializer(serializers.ModelSerializer):
    """CRUD admin d'une formule. `nb_actives`/`nb_en_attente`/`nb_pubs_total`
    sont lus depuis l'annotation posée par la vue (0 requête supplémentaire) ;
    en son absence (ex. juste après un create), calculés à la volée."""
    nb_actives = serializers.SerializerMethodField()
    nb_en_attente = serializers.SerializerMethodField()
    nb_pubs_total = serializers.SerializerMethodField()

    class Meta:
        model = FormulePublicite
        fields = [
            'id', 'nom', 'prix', 'priorite', 'est_active',
            'duree_jours', 'passages_par_jour', 'duree_affichage_secondes',
            'passages_par_type', 'quota_partenaires', 'acces_heures_affluence',
            'types_affichage', 'nb_images_max', 'video_autorisee',
            'duree_video_max_secondes', 'cible_pourcentage_actifs',
            'nb_actives', 'nb_en_attente', 'nb_pubs_total',
        ]

    def _compte(self, obj, nom_annotation, secours):
        valeur = getattr(obj, nom_annotation, None)
        if valeur is not None:
            return valeur
        return secours(obj)

    def get_nb_actives(self, obj):
        from .models import Publicite
        return self._compte(obj, 'nb_actives', lambda o: Publicite.objects.filter(
            formule=o, statut=Publicite.Statut.ACTIVE).count())

    def get_nb_en_attente(self, obj):
        from .models import Publicite
        def secours(o):
            return Publicite.objects.filter(formule=o, statut__in=[
                Publicite.Statut.EN_ATTENTE_PAIEMENT,
                Publicite.Statut.EN_ATTENTE_VALIDATION]).count()
        return self._compte(obj, 'nb_en_attente', secours)

    def get_nb_pubs_total(self, obj):
        from .models import Publicite
        def secours(o):
            return Publicite.objects.filter(formule=o).exclude(
                statut=Publicite.Statut.BROUILLON).count()
        return self._compte(obj, 'nb_pubs_total', secours)

    # ── Validations (messages français, par champ) ──────────────────

    def validate_nom(self, valeur):
        nom = (valeur or '').strip()
        if not nom:
            raise serializers.ValidationError('Le nom est requis.')
        qs = FormulePublicite.objects.filter(nom__iexact=nom)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f'Une formule « {nom} » existe déjà.')
        return nom

    def validate_prix(self, valeur):
        if valeur < 0:
            raise serializers.ValidationError('Le prix doit être positif ou nul.')
        return valeur

    def validate_duree_jours(self, valeur):
        if valeur < 1:
            raise serializers.ValidationError('La durée doit être d\'au moins 1 jour.')
        return valeur

    def validate_passages_par_jour(self, valeur):
        if valeur < 1:
            raise serializers.ValidationError(
                'Le nombre de passages par jour doit être d\'au moins 1.')
        return valeur

    def validate_duree_affichage_secondes(self, valeur):
        if valeur < 1:
            raise serializers.ValidationError(
                'La durée d\'un passage doit être d\'au moins 1 seconde.')
        return valeur

    def validate_quota_partenaires(self, valeur):
        # Aligne le contrat API sur un quota toujours strictement positif :
        # le back-office Django affiche « illimité » pour un quota <= 0
        # (apps/publicites/admin.py::FormuleAdmin.occupation), mais rien de
        # ce module n'utilise réellement cette valeur spéciale — 0 y est déjà
        # traité comme « aucune place » (quota_formule_disponible). On
        # n'accepte donc plus 0 depuis cette API pour éviter l'ambiguïté ;
        # l'affichage « illimité » de l'admin Django reste inchangé.
        if valeur < 1:
            raise serializers.ValidationError(
                'Le quota de partenaires simultanés doit être d\'au moins 1.')
        return valeur

    def validate_nb_images_max(self, valeur):
        if valeur < 1:
            raise serializers.ValidationError(
                'Le nombre d\'images maximum doit être d\'au moins 1.')
        return valeur

    def validate_cible_pourcentage_actifs(self, valeur):
        if valeur is not None and not (1 <= valeur <= 100):
            raise serializers.ValidationError(
                'La cible doit être un pourcentage entre 1 et 100, ou vide.')
        return valeur

    def validate_types_affichage(self, valeur):
        if not valeur:
            raise serializers.ValidationError(
                'Au moins un type d\'affichage est requis.')
        valides = {v for v, _ in TypeAffichage.choices}
        inconnus = sorted(set(valeur) - valides)
        if inconnus:
            raise serializers.ValidationError(
                f'Type(s) d\'affichage inconnu(s) : {", ".join(inconnus)}. '
                f'Valeurs possibles : {", ".join(sorted(valides))}.')
        return valeur

    def validate(self, attrs):
        types_affichage = attrs.get(
            'types_affichage',
            getattr(self.instance, 'types_affichage', None) or [])
        passages_par_type = attrs.get('passages_par_type')
        if passages_par_type:
            cles_inconnues = sorted(
                set(passages_par_type) - set(types_affichage))
            if cles_inconnues:
                raise serializers.ValidationError({'passages_par_type': (
                    f'Emplacement(s) hors de types_affichage : '
                    f'{", ".join(cles_inconnues)}.')})
            invalides = {
                k: v for k, v in passages_par_type.items()
                if not isinstance(v, int) or isinstance(v, bool) or v < 0}
            if invalides:
                raise serializers.ValidationError({'passages_par_type': (
                    'Chaque valeur doit être un entier positif ou nul '
                    f'(invalide pour : {", ".join(sorted(invalides))}).')})

        video_autorisee = attrs.get(
            'video_autorisee', getattr(self.instance, 'video_autorisee', False))
        duree_video = attrs.get(
            'duree_video_max_secondes',
            getattr(self.instance, 'duree_video_max_secondes', None))
        if video_autorisee and (duree_video is None or duree_video < 1):
            raise serializers.ValidationError({'duree_video_max_secondes': (
                'Requise (au moins 1 seconde) quand la vidéo est autorisée.')})
        return attrs


class ParametresPubliciteAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParametresPublicite
        fields = [
            'id', 'affluence_debut', 'affluence_fin', 'calcul_affluence_auto',
            'intervalle_min_interstitiel_secondes', 'validation_auto',
            'interstitiel_minute_min', 'interstitiel_minute_max',
            'interstitiel_ratio_session_courte',
        ]
        read_only_fields = ['id']

    def validate_interstitiel_ratio_session_courte(self, valeur):
        if not (1 <= valeur <= 100):
            raise serializers.ValidationError(
                'Doit être un pourcentage entre 1 et 100.')
        return valeur

    def validate(self, attrs):
        mini = attrs.get(
            'interstitiel_minute_min',
            getattr(self.instance, 'interstitiel_minute_min', 0))
        maxi = attrs.get(
            'interstitiel_minute_max',
            getattr(self.instance, 'interstitiel_minute_max', 0))
        if maxi < mini:
            raise serializers.ValidationError({'interstitiel_minute_max': (
                'Doit être supérieure ou égale à la minute nominale '
                '(interstitiel_minute_min).')})
        debut = attrs.get(
            'affluence_debut', getattr(self.instance, 'affluence_debut', None))
        fin = attrs.get(
            'affluence_fin', getattr(self.instance, 'affluence_fin', None))
        if debut is not None and fin is not None and debut == fin:
            raise serializers.ValidationError({'affluence_fin': (
                'L\'heure de fin doit être différente de l\'heure de début.')})
        return attrs
