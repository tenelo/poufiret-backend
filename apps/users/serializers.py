"""
Serializers de l'app users : authentification et profil.
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, SessionAppareil, ProfilPartenaire, NumeroVerifie, CodeOTP


class UtilisateurSerializer(serializers.ModelSerializer):
    """Représentation publique d'un utilisateur (lecture/édition profil)."""
    departement_nom = serializers.CharField(
        source='departement.nom', read_only=True, default='')
    region_nom = serializers.CharField(
        source='departement.region.nom', read_only=True, default='')

    class Meta:
        model = User
        fields = [
            'id', 'telephone', 'username', 'first_name', 'last_name',
            'role', 'est_verifie', 'pin_par_defaut', 'langue_preferee', 'token_fcm',
            'departement', 'departement_nom', 'region_nom',
            'tranche_age', 'sexe',
        ]
        read_only_fields = ['id', 'telephone', 'role', 'est_verifie', 'pin_par_defaut',
                            'departement_nom', 'region_nom']


class ConnexionSerializer(TokenObtainPairSerializer):
    """
    Connexion par téléphone + mot de passe.
    Retourne access + refresh, enrichis des infos utilisateur.
    """
    def validate(self, attrs):
        data = super().validate(attrs)
        data['utilisateur'] = UtilisateurSerializer(self.user).data
        return data


class LogoutSerializer(serializers.Serializer):
    """Déconnexion volontaire : blackliste le refresh token fourni."""
    refresh = serializers.CharField()

    def save(self, **kwargs):
        try:
            RefreshToken(self.validated_data['refresh']).blacklist()
        except Exception:
            raise serializers.ValidationError(
                {'refresh': 'Token invalide ou déjà expiré.'}
            )


class InscriptionSerializer(serializers.ModelSerializer):
    """
    Inscription d'un nouvel utilisateur (rôle client par défaut).
    Le passage partenaire se fait via un flux séparé.
    """
    # Le mot de passe EST un PIN a 4 chiffres (stocke hashe via set_password).
    password = serializers.CharField(write_only=True, min_length=4, max_length=4)

    class Meta:
        model = User
        fields = ['telephone', 'username', 'first_name', 'last_name', 'password', 'departement', 'tranche_age', 'sexe']
        extra_kwargs = {
            'departement': {'required': False},
            'tranche_age': {'required': False},
            'sexe': {'required': False},
        }

    def validate_password(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from rest_framework import serializers as drf_serializers
        from apps.core.validateurs import valider_pin
        try:
            return valider_pin(value)
        except DjangoValidationError as e:
            raise drf_serializers.ValidationError(e.messages)

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.role = User.Role.CLIENT
        user.set_password(password)
        user.save()
        return user


class SessionAppareilSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionAppareil
        fields = ['id', 'appareil_nom', 'appareil_id', 'plateforme',
                  'adresse_ip', 'derniere_activite_le', 'est_active', 'cree_le']
        read_only_fields = fields


class DevenirPartenaireSerializer(serializers.ModelSerializer):
    """Crée le ProfilPartenaire d'un client. Rôle partenaire immédiat,
    mais profil EN_ATTENTE + invisible jusqu'à validation admin."""
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
        help_text="IDs des categories. La premiere devient la principale. "
                  "Si vide, deduite du type_partenaire.",
    )

    class Meta:
        model = ProfilPartenaire
        fields = ['type_partenaire', 'nom_commerce', 'description', 'adresse',
                  'quartier', 'secteur', 'ville', 'departement',
                  'telephone_pro', 'whatsapp', 'email_pro', 'categories']

    def validate_categories(self, ids):
        from apps.catalog.models import Categorie
        if not ids:
            return ids
        existantes = set(Categorie.objects.filter(
            id__in=ids, est_active=True).values_list('id', flat=True))
        inconnues = [i for i in ids if i not in existantes]
        if inconnues:
            raise serializers.ValidationError(
                f'Categories inconnues ou inactives : {inconnues}')
        return ids

    def create(self, validated_data):
        from .models import PlanAbonnement
        categories = validated_data.pop('categories', [])
        user = self.context['request'].user
        if hasattr(user, 'profil_partenaire'):
            raise serializers.ValidationError("Vous avez déjà un profil partenaire.")
        plan, _ = PlanAbonnement.objects.get_or_create(
            code='basique', duree_jours=-1,
            defaults={'libelle': 'Basique', 'prix': 0,
                      'nb_articles_max': 10, 'nb_photos_par_article': 1})
        profil = ProfilPartenaire.objects.create(
            user=user, plan=plan,
            statut=ProfilPartenaire.Statut.EN_ATTENTE,
            est_visible=False, **validated_data)
        user.role = User.Role.PARTENAIRE
        user.save(update_fields=['role'])
        self._rattacher_categories(profil, categories)
        return profil

    @staticmethod
    def _rattacher_categories(profil, ids):
        """Cree les liens PartenaireCategorie.

        Si aucune categorie choisie, on deduit celle qui declare ce
        type_partenaire (champ Categorie.types_partenaire).
        """
        from apps.catalog.models import Categorie, PartenaireCategorie
        if not ids:
            ids = list(
                Categorie.objects.filter(
                    est_active=True,
                    types_partenaire__contains=profil.type_partenaire,
                ).values_list('id', flat=True)[:1]
            )
        for rang, cid in enumerate(ids):
            PartenaireCategorie.objects.get_or_create(
                partenaire=profil, categorie_id=cid,
                defaults={'est_principale': rang == 0},
            )


class VitrinePartenaireSerializer(serializers.ModelSerializer):
    """Représentation PUBLIQUE d'un partenaire (vitrine côté client).
    Lecture seule. N'expose aucun champ sensible (plan, abonnement, GPS)."""
    nombre_likes = serializers.SerializerMethodField()
    est_like_par_moi = serializers.SerializerMethodField()
    est_favori_par_moi = serializers.SerializerMethodField()
    type_partenaire_libelle = serializers.CharField(
        source='get_type_partenaire_display', read_only=True)
    departement = serializers.CharField(
        source='departement.nom', read_only=True, default='')
    region = serializers.CharField(
        source='departement.region.nom', read_only=True, default='')

    class Meta:
        model = ProfilPartenaire
        fields = [
            'id', 'nom_commerce', 'type_partenaire', 'type_partenaire_libelle',
            'description', 'logo', 'photo_couverture',
            'adresse', 'quartier', 'secteur', 'ville', 'departement', 'region', 'description_acces',
            'telephone_pro', 'whatsapp', 'email_pro',
            'nombre_likes', 'nb_vues', 'est_like_par_moi', 'est_favori_par_moi',
        ]
        read_only_fields = fields

    def get_nombre_likes(self, obj):
        return obj.likes.count() if hasattr(obj, 'likes') else 0

    def get_est_like_par_moi(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.likes.filter(user=user).exists() if hasattr(obj, 'likes') else False

    def get_est_favori_par_moi(self, obj):
        user = self.context['request'].user
        if not user.is_authenticated:
            return False
        return obj.favoris.filter(user=user).exists() if hasattr(obj, 'favoris') else False


class MonProfilPartenaireSerializer(serializers.ModelSerializer):
    """Profil du partenaire connecte : lecture et modification.

    Les champs de controle (statut, visibilite, plan, faveur, badge) sont
    en lecture seule : ils relevent de l'administration, pas du partenaire.
    """
    plan_libelle = serializers.CharField(source='plan.libelle', read_only=True)
    nb_photos_par_article = serializers.IntegerField(
        source='plan.nb_photos_par_article', read_only=True)
    nb_articles_max = serializers.IntegerField(
        source='plan.nb_articles_max', read_only=True)
    type_partenaire_libelle = serializers.CharField(
        source='get_type_partenaire_display', read_only=True)
    statut_libelle = serializers.CharField(
        source='get_statut_display', read_only=True)

    class Meta:
        model = ProfilPartenaire
        fields = [
            'id', 'nom_commerce', 'description', 'logo', 'photo_couverture',
            'type_partenaire', 'type_partenaire_libelle',
            'adresse', 'quartier', 'secteur', 'ville', 'description_acces',
            'telephone_pro', 'whatsapp', 'email_pro',
            # Lecture seule : pilotes par l'administration
            'statut', 'statut_libelle', 'est_visible', 'badge_certifie',
            'est_faveur', 'plan_libelle', 'abonnement_fin', 'nb_vues',
            'nb_photos_par_article', 'nb_articles_max',
        ]
        read_only_fields = [
            'id', 'statut', 'statut_libelle', 'est_visible', 'badge_certifie',
            'est_faveur', 'plan_libelle', 'abonnement_fin', 'nb_vues',
            'type_partenaire_libelle', 'nb_photos_par_article',
            'nb_articles_max',
        ]


class MaCategorieSerializer(serializers.ModelSerializer):
    """Rattachement du partenaire a une categorie, avec son image dediee."""
    categorie_nom = serializers.CharField(source='categorie.nom', read_only=True)
    categorie_slug = serializers.CharField(source='categorie.slug', read_only=True)
    categorie_icone = serializers.CharField(source='categorie.icone', read_only=True)

    class Meta:
        from apps.catalog.models import PartenaireCategorie as _PC
        model = _PC
        fields = ['id', 'categorie', 'categorie_nom', 'categorie_slug',
                  'categorie_icone', 'est_principale', 'image_couverture']
        read_only_fields = ['id', 'categorie', 'est_principale']


class DemandeOTPSerializer(serializers.Serializer):
    """
    Demande d'un code OTP. Logique anti-facture :
    - but=inscription : si le numero est DEJA verifie -> aucun SMS,
      on signale deja_verifie=True (Flutter enchaine sur le choix du PIN).
    - but=reinit_pin  : OTP meme si numero connu (option A), mais SEULEMENT
      si un compte existe pour ce numero.
    """
    telephone = serializers.CharField(max_length=20)
    but = serializers.ChoiceField(
        choices=CodeOTP.But.choices, default=CodeOTP.But.INSCRIPTION,
    )

    def validate_telephone(self, v):
        v = v.strip()
        if not v.startswith('+'):
            raise serializers.ValidationError(
                "Numéro au format international attendu (+225...).")
        return v

    def creer_et_envoyer(self):
        from apps.core.sms import envoyer_sms
        tel = self.validated_data['telephone']
        but = self.validated_data['but']
        deja_verifie = NumeroVerifie.objects.filter(telephone=tel).exists()
        compte_existe = User.objects.filter(telephone=tel).exists()

        if but == CodeOTP.But.INSCRIPTION:
            if deja_verifie:
                # Numero connu -> pas de SMS. Flutter passe direct au PIN.
                return {'deja_verifie': True, 'compte_existe': compte_existe,
                        'otp_envoye': False}
            # Numero inconnu -> on genere et on envoie.
        else:  # REINIT_PIN
            if not compte_existe:
                raise serializers.ValidationError(
                    {'telephone': "Aucun compte n'existe pour ce numéro."})
            # Option A : on (re)envoie un OTP meme si connu.

        code = CodeOTP.generer(tel, but=but)
        envoyer_sms(tel, f"Poufiret : votre code de vérification est {code.code}")
        return {'deja_verifie': False, 'compte_existe': compte_existe,
                'otp_envoye': True}


class VerifierOTPSerializer(serializers.Serializer):
    """
    Verifie un code OTP. Incremente les tentatives, et sur succes :
    pose valide_le, inscrit le numero dans NumeroVerifie (source otp).
    """
    telephone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=4)
    but = serializers.ChoiceField(
        choices=CodeOTP.But.choices, default=CodeOTP.But.INSCRIPTION,
    )

    def validate(self, attrs):
        from django.utils import timezone
        tel = attrs['telephone'].strip()
        but = attrs['but']
        otp = CodeOTP.objects.filter(
            telephone=tel, but=but, est_utilise=False,
        ).order_by('-cree_le').first()

        if otp is None:
            raise serializers.ValidationError(
                {'code': "Aucun code actif. Demandez un nouveau code."})
        if not otp.est_valide():
            raise serializers.ValidationError(
                {'code': "Code expiré ou trop de tentatives. Demandez un nouveau code."})

        otp.tentatives += 1
        if otp.code != attrs['code'].strip():
            otp.save(update_fields=['tentatives', 'modifie_le'])
            restant = max(0, otp.MAX_TENTATIVES - otp.tentatives)
            raise serializers.ValidationError(
                {'code': f"Code incorrect. Essais restants : {restant}."})

        # Succes : on marque valide, on garde est_utilise=False pour l'etape PIN.
        otp.valide_le = timezone.now()
        otp.save(update_fields=['tentatives', 'valide_le', 'modifie_le'])

        # Le numero est desormais prouve -> registre anti-double-OTP.
        NumeroVerifie.objects.get_or_create(
            telephone=tel,
            defaults={'source': NumeroVerifie.Source.OTP},
        )
        self._otp = otp
        return attrs


class DefinirPINSerializer(serializers.Serializer):
    """
    Definit (inscription) ou reinitialise (reinit_pin) le PIN, apres preuve
    d'un OTP valide recemment (option B : CodeOTP.valide_le recent, non consomme).
    """
    telephone = serializers.CharField(max_length=20)
    password = serializers.CharField(min_length=4, max_length=4, write_only=True)
    but = serializers.ChoiceField(
        choices=CodeOTP.But.choices, default=CodeOTP.But.INSCRIPTION,
    )
    # Champs profil facultatifs pour l'inscription
    username = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_password(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from apps.core.validateurs import valider_pin
        try:
            return valider_pin(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)

    def validate(self, attrs):
        from django.utils import timezone
        from datetime import timedelta
        tel = attrs['telephone'].strip()
        but = attrs['but']
        limite = timezone.now() - timedelta(minutes=CodeOTP.FENETRE_PREUVE_MINUTES)
        otp = CodeOTP.objects.filter(
            telephone=tel, but=but, valide_le__isnull=False,
            valide_le__gte=limite, pin_consomme=False,
        ).order_by('-valide_le').first()
        if otp is None:
            raise serializers.ValidationError(
                "Vérification OTP requise ou expirée. Recommencez la vérification.")
        self._otp = otp
        return attrs

    def save(self, **kwargs):
        tel = self.validated_data['telephone'].strip()
        but = self.validated_data['but']
        pin = self.validated_data['password']

        if but == CodeOTP.But.INSCRIPTION:
            if User.objects.filter(telephone=tel).exists():
                raise serializers.ValidationError(
                    {'telephone': "Un compte existe déjà pour ce numéro."})
            user = User(
                telephone=tel,
                username=self.validated_data.get('username') or tel,
                first_name=self.validated_data.get('first_name', ''),
                last_name=self.validated_data.get('last_name', ''),
                role=User.Role.CLIENT,
                est_verifie=True,
                pin_par_defaut=False,
            )
            user.set_password(pin)
            user.save()
        else:  # REINIT_PIN
            try:
                user = User.objects.get(telephone=tel)
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {'telephone': "Aucun compte pour ce numéro."})
            user.set_password(pin)
            user.pin_par_defaut = False
            user.est_verifie = True
            user.save(update_fields=['password', 'pin_par_defaut', 'est_verifie'])

        # Consomme la preuve : cet OTP ne peut plus reservir.
        self._otp.est_utilise = True
        self._otp.pin_consomme = True
        self._otp.save(update_fields=['est_utilise', 'pin_consomme', 'modifie_le'])
        self.user = user
        return user


class CreerPartenaireParAdminSerializer(serializers.Serializer):
    """
    Creation COMPLETE d'un partenaire par un admin/demarcheur :
    User + ProfilPartenaire ACTIF et visible immediatement.

    - Le numero n'a pas d'OTP : on considere la verification faite de visu.
      -> inscrit dans NumeroVerifie (source admin), est_verifie=True.
    - PIN par defaut ALEATOIRE 4 chiffres + pin_par_defaut=True
      -> le partenaire le change a sa 1re connexion (ecran bloquant Flutter).
    - Le PIN en clair est renvoye UNE fois dans la reponse, l'admin le lit
      au partenaire.
    """
    # Identite (User)
    telephone = serializers.CharField(max_length=20)
    prenom = serializers.CharField(max_length=100, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Profil partenaire
    type_partenaire = serializers.CharField()
    nom_commerce = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    adresse = serializers.CharField(required=False, allow_blank=True)
    quartier = serializers.CharField(required=False, allow_blank=True)
    secteur = serializers.CharField(required=False, allow_blank=True)
    ville = serializers.CharField(required=False, allow_blank=True)
    departement = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.geo.models', fromlist=['Departement']).Departement.objects.all(),
        required=False, allow_null=True,
    )
    telephone_pro = serializers.CharField(max_length=20, required=False, allow_blank=True)
    whatsapp = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email_pro = serializers.EmailField(required=False, allow_blank=True)
    plan_id = serializers.IntegerField(
        required=False,
        help_text="Plan a assigner. Si absent, Basique par defaut.",
    )
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )

    def validate_telephone(self, v):
        v = v.strip()
        if not v.startswith('+'):
            raise serializers.ValidationError(
                "Numéro au format international attendu (+225...).")
        if User.objects.filter(telephone=v).exists():
            raise serializers.ValidationError(
                "Un compte existe déjà pour ce numéro.")
        return v

    def validate_categories(self, ids):
        from apps.catalog.models import Categorie
        if not ids:
            return ids
        existantes = set(Categorie.objects.filter(
            id__in=ids, est_active=True).values_list('id', flat=True))
        inconnues = [i for i in ids if i not in existantes]
        if inconnues:
            raise serializers.ValidationError(
                f'Categories inconnues ou inactives : {inconnues}')
        return ids

    def create(self, validated_data):
        import random
        from django.db import transaction
        from .models import PlanAbonnement, ProfilPartenaire

        categories = validated_data.pop('categories', [])
        plan_id = validated_data.pop('plan_id', None)
        tel = validated_data.pop('telephone')
        prenom = validated_data.pop('prenom', '')
        nom = validated_data.pop('nom', '')

        # PIN par defaut aleatoire non trivial
        pin = f'{random.randint(0, 9999):04d}'
        while pin in {'0000', '1111', '1234'}:
            pin = f'{random.randint(0, 9999):04d}'

        # Plan : celui demande, sinon Basique
        if plan_id:
            try:
                plan = PlanAbonnement.objects.get(pk=plan_id)
            except PlanAbonnement.DoesNotExist:
                raise serializers.ValidationError(
                    {'plan_id': "Plan introuvable."})
        else:
            plan, _ = PlanAbonnement.objects.get_or_create(
                code='basique', duree_jours=-1,
                defaults={'libelle': 'Basique', 'prix': 0,
                          'nb_articles_max': 10, 'nb_photos_par_article': 1})

        with transaction.atomic():
            user = User(
                telephone=tel,
                username=tel,
                first_name=prenom,
                last_name=nom,
                role=User.Role.PARTENAIRE,
                est_verifie=True,
                pin_par_defaut=True,
            )
            user.set_password(pin)
            user.save()

            NumeroVerifie.objects.get_or_create(
                telephone=tel,
                defaults={'nom': nom, 'prenom': prenom,
                          'source': NumeroVerifie.Source.ADMIN},
            )

            profil = ProfilPartenaire.objects.create(
                user=user, plan=plan,
                statut=ProfilPartenaire.Statut.ACTIF,
                est_visible=True,
                **validated_data,
            )
            DevenirPartenaireSerializer._rattacher_categories(profil, categories)

        self._pin_clair = pin
        self._user = user
        self._profil = profil
        return profil

    def to_representation(self, instance):
        return {
            'partenaire_id': str(self._user.id),
            'telephone': self._user.telephone,
            'nom_commerce': self._profil.nom_commerce,
            'statut': self._profil.statut,
            'pin_par_defaut': self._pin_clair,
            'message': (f"Partenaire créé. Communiquez ce code au partenaire : "
                        f"{self._pin_clair}. Il devra le changer à sa première "
                        f"connexion."),
        }
