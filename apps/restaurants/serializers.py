"""Serializers du module restaurants (Phase R1).

Mêmes serializers pour l'espace restaurateur (/restaurants/mon-restaurant/)
et l'espace admin (/restaurants/admin/<id>/) — seule la vue qui les
instancie change de périmètre (voir views_prive.py). Les serializers de
lecture publique (carte, liste, détail) sont distincts, par construction
plus légers et sans les champs de gestion interne.
"""
from rest_framework import serializers

from apps.catalog.models import Article, GroupeOption, OptionGroupe, SectionMenu, Variante
from apps.users.models import HoraireOuverture

from . import services
from .models import (
    LigneMenu, MenuProgramme, ModeService, ProfilRestaurant, TelephoneRestaurant,
)


def image_plat(article):
    """Image d'un plat : l'image principale active, sinon la première image
    active par ordre (puis id), sinon None. Lit article.images.all() pour
    profiter du prefetch posé par les vues (pas de requête par plat)."""
    images = [i for i in article.images.all() if i.est_active and i.image]
    if not images:
        return None
    principale = next((i for i in images if i.est_principale), None)
    return principale or min(images, key=lambda i: (i.ordre, i.id))


def url_image_plat(article, requete):
    """URL ABSOLUE (si requête fournie) de image_plat(article), ou None."""
    img = image_plat(article)
    if img is None:
        return None
    return requete.build_absolute_uri(img.image.url) if requete else img.image.url


def urls_images_plat(article, requete):
    """URL ABSOLUES (si requête fournie) de toutes les images actives du plat :
    la principale en premier, puis par ordre (id en départage). Même source
    que image_plat (article.images.all(), prefetch des vues : 0 requête)."""
    images = sorted((i for i in article.images.all() if i.est_active and i.image),
                    key=lambda i: (not i.est_principale, i.ordre, i.id))
    return [requete.build_absolute_uri(i.image.url) if requete else i.image.url for i in images]


def _cle_tri(obj):
    """Tri « ordre puis nom » (insensible à la casse), id en départage."""
    return (obj.ordre, (obj.nom or '').casefold(), obj.id)


# ═══════════════════════════════════════════════════════════════════════
# FICHE (restaurateur / admin)
# ═══════════════════════════════════════════════════════════════════════

class HoraireOuvertureSerializer(serializers.ModelSerializer):
    class Meta:
        model = HoraireOuverture
        fields = ['id', 'jour_semaine', 'ouvert', 'heure_ouverture', 'heure_fermeture',
                  'pause_debut', 'pause_fin', 'note']


class _HeureOptionnelle(serializers.TimeField):
    """Heure facultative : absente, null ou "" → None (jour fermé, champ vidé
    côté formulaire)."""
    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, default=None, **kwargs)

    def to_internal_value(self, value):
        if value in ('', None):
            return None
        return super().to_internal_value(value)


class HoraireEcritureSerializer(serializers.Serializer):
    """Un élément du PUT .../horaires/ (validation seule ; l'écriture est un
    upsert par jour_semaine dans la vue)."""
    jour_semaine = serializers.ChoiceField(choices=HoraireOuverture.Jour.choices)
    ouvert = serializers.BooleanField(required=False, default=True)
    heure_ouverture = _HeureOptionnelle()
    heure_fermeture = _HeureOptionnelle()
    pause_debut = _HeureOptionnelle()
    pause_fin = _HeureOptionnelle()
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True,
                                 max_length=200, default='')

    def validate_note(self, valeur):
        return valeur or ''


class TelephoneRestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelephoneRestaurant
        fields = ['id', 'libelle', 'numero', 'ordre']
        read_only_fields = ['id']


class ProfilRestaurantSerializer(serializers.ModelSerializer):
    """Fiche restaurant. Les champs déjà portés par ProfilPartenaire
    (nom_commerce, logo, photo_couverture, adresse, quartier, ville,
    telephone_pro, whatsapp) sont exposés en lecture, non dupliqués — leur
    édition reste sur /auth/mon-profil-partenaire/, inchangé."""
    partenaire_id = serializers.IntegerField(read_only=True)
    nom_commerce = serializers.CharField(source='partenaire.nom_commerce', read_only=True)
    logo = serializers.ImageField(source='partenaire.logo', read_only=True)
    photo_couverture = serializers.ImageField(source='partenaire.photo_couverture', read_only=True)
    adresse = serializers.CharField(source='partenaire.adresse', read_only=True)
    quartier = serializers.CharField(source='partenaire.quartier', read_only=True)
    ville = serializers.CharField(source='partenaire.ville', read_only=True)
    localite_id = serializers.IntegerField(source='partenaire.localite.id', read_only=True, default=None)
    localite_nom = serializers.CharField(source='partenaire.localite.nom', read_only=True, default=None)
    quartier_id = serializers.IntegerField(source='partenaire.quartier_geo.id', read_only=True, default=None)
    quartier_nom = serializers.CharField(source='partenaire.quartier_geo.nom', read_only=True, default=None)
    telephone_pro = serializers.CharField(source='partenaire.telephone_pro', read_only=True)
    whatsapp = serializers.CharField(source='partenaire.whatsapp', read_only=True)

    horaires = serializers.SerializerMethodField()
    telephones = TelephoneRestaurantSerializer(many=True, read_only=True)

    est_ouvert = serializers.SerializerMethodField()
    prochaine_ouverture = serializers.SerializerMethodField()
    message_statut = serializers.SerializerMethodField()

    class Meta:
        model = ProfilRestaurant
        fields = ['id', 'partenaire_id', 'nom_commerce', 'logo', 'photo_couverture',
                  'adresse', 'quartier', 'ville', 'localite_id', 'localite_nom',
                  'quartier_id', 'quartier_nom', 'telephone_pro', 'whatsapp',
                  'ferme_exceptionnellement', 'motif_fermeture', 'ferme_jusqu_au',
                  'services', 'delai_preparation_min', 'adresse_reperes',
                  'facebook', 'instagram', 'tiktok', 'specialites',
                  'horaires', 'telephones',
                  'est_ouvert', 'prochaine_ouverture', 'message_statut',
                  'modifie_par_role', 'modifie_par_nom', 'modifie_le', 'cree_le']
        read_only_fields = ['modifie_par_role', 'modifie_par_nom', 'modifie_le', 'cree_le']

    def get_horaires(self, obj):
        return HoraireOuvertureSerializer(
            obj.partenaire.horaires.order_by('jour_semaine'), many=True).data

    def get_est_ouvert(self, obj):
        return services.est_ouvert(obj)

    def get_prochaine_ouverture(self, obj):
        p = services.prochaine_ouverture(obj)
        return p.isoformat() if p else None

    def get_message_statut(self, obj):
        return services.message_statut(obj)

    def validate_services(self, valeur):
        valides = {v for v, _l in ModeService.choices}
        inconnus = sorted(set(valeur) - valides)
        if inconnus:
            raise serializers.ValidationError(
                f'Service(s) inconnu(s) : {", ".join(inconnus)}. '
                f'Valeurs possibles : {", ".join(sorted(valides))}.')
        return valeur


# ═══════════════════════════════════════════════════════════════════════
# MENUS PROGRAMMÉS (restaurateur / admin)
# ═══════════════════════════════════════════════════════════════════════

class LigneMenuSerializer(serializers.ModelSerializer):
    plat_nom = serializers.CharField(source='plat.nom', read_only=True)
    plat_image = serializers.SerializerMethodField()
    plat_images = serializers.SerializerMethodField()
    prix_effectif = serializers.DecimalField(max_digits=12, decimal_places=0, read_only=True)
    stock_restant = serializers.SerializerMethodField()
    est_epuise = serializers.SerializerMethodField()

    class Meta:
        model = LigneMenu
        fields = ['id', 'menu', 'plat', 'plat_nom', 'plat_image', 'plat_images', 'prix_menu',
                  'prix_effectif', 'stock_initial', 'stock_restant', 'est_epuise',
                  'ordre', 'modifie_par_role', 'modifie_par_nom', 'modifie_le']
        read_only_fields = ['modifie_par_role', 'modifie_par_nom', 'modifie_le']

    def get_plat_image(self, obj):
        return url_image_plat(obj.plat, self.context.get('request'))

    def get_plat_images(self, obj):
        return urls_images_plat(obj.plat, self.context.get('request'))

    def get_stock_restant(self, obj):
        return services.stock_restant(obj)

    def get_est_epuise(self, obj):
        return services.plat_epuise(obj)

    def validate_plat(self, article):
        if self.instance is not None:
            menu = self.instance.menu
        else:
            menu_id = self.initial_data.get('menu')
            menu = MenuProgramme.objects.filter(pk=menu_id).first() if menu_id else None
        if menu is not None and article.partenaire_id != menu.restaurant.partenaire_id:
            raise serializers.ValidationError(
                "Ce plat n'appartient pas au restaurant de ce menu.")
        return article


class MenuProgrammeSerializer(serializers.ModelSerializer):
    lignes = serializers.SerializerMethodField()
    commandable = serializers.SerializerMethodField()

    class Meta:
        model = MenuProgramme
        fields = ['id', 'restaurant', 'nature', 'jour_semaine', 'date', 'service',
                  'heure_debut', 'heure_fin', 'titre', 'publie',
                  'heure_limite_commande', 'lignes', 'commandable',
                  'modifie_par_role', 'modifie_par_nom', 'modifie_le', 'cree_le']
        read_only_fields = ['restaurant', 'modifie_par_role', 'modifie_par_nom',
                            'modifie_le', 'cree_le']

    def get_lignes(self, obj):
        lignes = (obj.lignes.select_related('plat').prefetch_related('plat__images')
                  .order_by('ordre', 'id'))
        return LigneMenuSerializer(lignes, many=True, context=self.context).data

    def get_commandable(self, obj):
        return services.menu_commandable(obj)

    def validate(self, attrs):
        nature = attrs.get('nature', getattr(self.instance, 'nature', None))
        jour = attrs.get('jour_semaine', getattr(self.instance, 'jour_semaine', None))
        date_ = attrs.get('date', getattr(self.instance, 'date', None))
        if nature == MenuProgramme.Nature.HEBDOMADAIRE:
            if not jour:
                raise serializers.ValidationError(
                    {'jour_semaine': 'Requis quand nature = hebdomadaire.'})
            if not (1 <= jour <= 7):
                raise serializers.ValidationError(
                    {'jour_semaine': 'Doit être compris entre 1 (lundi) et 7 (dimanche).'})
            attrs['date'] = None
        elif nature == MenuProgramme.Nature.DATE:
            if not date_:
                raise serializers.ValidationError({'date': 'Requise quand nature = date.'})
            attrs['jour_semaine'] = None
        heure_debut = attrs.get('heure_debut', getattr(self.instance, 'heure_debut', None))
        heure_fin = attrs.get('heure_fin', getattr(self.instance, 'heure_fin', None))
        if heure_debut and heure_fin and heure_fin <= heure_debut:
            raise serializers.ValidationError(
                {'heure_fin': 'Doit être postérieure à heure_debut.'})
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# LECTURE PUBLIQUE — carte (sections → plats → variantes → groupes d'options)
# ═══════════════════════════════════════════════════════════════════════

class VariantePubliqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variante
        fields = ['id', 'nom', 'prix_supplement', 'est_par_defaut']


class OptionGroupePubliqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionGroupe
        fields = ['id', 'nom', 'prix_supplement']


class GroupeOptionPubliqueSerializer(serializers.ModelSerializer):
    options = serializers.SerializerMethodField()

    class Meta:
        model = GroupeOption
        fields = ['id', 'libelle', 'min_choix', 'max_choix', 'options']

    def get_options(self, obj):
        return OptionGroupePubliqueSerializer(
            obj.options.filter(est_actif=True).order_by('ordre'), many=True).data


class PlatCartePubliqueSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    variantes = serializers.SerializerMethodField()
    groupes_options = serializers.SerializerMethodField()
    est_epuise = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'nom', 'slug', 'description', 'prix', 'prix_promotion',
                  'image', 'images', 'est_disponible', 'est_epuise', 'variantes', 'groupes_options']

    def get_image(self, obj):
        return url_image_plat(obj, self.context.get('request'))

    def get_images(self, obj):
        return urls_images_plat(obj, self.context.get('request'))

    def get_variantes(self, obj):
        return VariantePubliqueSerializer(
            obj.variantes.filter(est_active=True).order_by('ordre'), many=True).data

    def get_groupes_options(self, obj):
        return GroupeOptionPubliqueSerializer(
            obj.groupes_options.filter(est_actif=True).order_by('ordre'), many=True,
            context=self.context).data

    def get_est_epuise(self, obj):
        return not obj.est_disponible


class SectionCartePubliqueSerializer(serializers.ModelSerializer):
    plats = serializers.SerializerMethodField()

    class Meta:
        model = SectionMenu
        fields = ['id', 'nom', 'icone', 'ordre', 'plats']

    def get_plats(self, obj):
        plats = sorted((a for a in obj.articles.all()
                        if a.est_actif and not a.est_reserve_aux_menus), key=_cle_tri)
        return PlatCartePubliqueSerializer(plats, many=True, context=self.context).data


# ═══════════════════════════════════════════════════════════════════════
# LECTURE PUBLIQUE — liste / détail restaurant
# ═══════════════════════════════════════════════════════════════════════

def _url_absolue(champ, requete):
    if not champ:
        return None
    try:
        return requete.build_absolute_uri(champ.url) if requete else champ.url
    except ValueError:
        return None


def _statut_de(partenaire):
    if not hasattr(partenaire, '_statut_restaurant'):
        partenaire._statut_restaurant = services.statut(partenaire.fiche)
    return partenaire._statut_restaurant


def _resume_menu_du_jour(fiche):
    """2-3 plats avec prix et photo, pour la carte liste (résumé)."""
    menus = services.menus_en_vigueur_maintenant(fiche) or services.menus_du_jour(fiche)
    menu = next((m for m in menus.values() if m), None)
    if menu is None:
        return None
    lignes = list(menu.lignes.select_related('plat').prefetch_related('plat__images')
                  .order_by('ordre', 'id')[:3])
    plats = []
    for ligne in lignes:
        plats.append({
            'nom': ligne.plat.nom,
            'prix': ligne.prix_effectif,
            'image': url_image_plat(ligne.plat, None),
        })
    return {'id': menu.id, 'titre': menu.titre, 'service': menu.service, 'plats': plats}


class RestaurantListeSerializer(serializers.Serializer):
    """Une ligne de GET /restaurants/?departement=."""
    id = serializers.IntegerField()
    nom = serializers.CharField(source='nom_commerce')
    localite_id = serializers.IntegerField(source='localite.id', read_only=True, default=None)
    localite_nom = serializers.CharField(source='localite.nom', read_only=True, default=None)
    quartier_id = serializers.IntegerField(source='quartier_geo.id', read_only=True, default=None)
    quartier_nom = serializers.CharField(source='quartier_geo.nom', read_only=True, default=None)
    logo = serializers.SerializerMethodField()
    couverture = serializers.SerializerMethodField()
    est_ouvert = serializers.SerializerMethodField()
    prochaine_ouverture = serializers.SerializerMethodField()
    message_statut = serializers.SerializerMethodField()
    delai_preparation_min = serializers.IntegerField(source='fiche.delai_preparation_min')
    services = serializers.ListField(source='fiche.services')
    specialites = serializers.ListField(source='fiche.specialites')
    menu_du_jour = serializers.SerializerMethodField()

    def _url(self, champ):
        return _url_absolue(champ, self.context.get('request'))

    def get_logo(self, obj):
        return self._url(obj.logo)

    def get_couverture(self, obj):
        return self._url(obj.photo_couverture)

    def get_est_ouvert(self, obj):
        return _statut_de(obj)['est_ouvert']

    def get_prochaine_ouverture(self, obj):
        return _statut_de(obj)['prochaine_ouverture']

    def get_message_statut(self, obj):
        return _statut_de(obj)['message_statut']

    def get_menu_du_jour(self, obj):
        return _resume_menu_du_jour(obj.fiche)


class RestaurantDetailPubliqueSerializer(serializers.Serializer):
    """GET /restaurants/<id>/ — fiche complète + menus en vigueur + carte,
    en une seule réponse (sans N+1 : les sections/plats/variantes/groupes
    sont préchargés par la vue)."""
    id = serializers.IntegerField()
    nom = serializers.CharField(source='nom_commerce')
    description = serializers.CharField()
    logo = serializers.SerializerMethodField()
    couverture = serializers.SerializerMethodField()
    adresse = serializers.CharField()
    quartier = serializers.CharField()
    ville = serializers.CharField()
    telephone_pro = serializers.CharField()
    whatsapp = serializers.CharField()
    localite_id = serializers.IntegerField(source='localite.id', read_only=True, default=None)
    localite_nom = serializers.CharField(source='localite.nom', read_only=True, default=None)
    quartier_id = serializers.IntegerField(source='quartier_geo.id', read_only=True, default=None)
    quartier_nom = serializers.CharField(source='quartier_geo.nom', read_only=True, default=None)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    position_modifiee_le = serializers.DateTimeField(read_only=True)
    position_modifiee_par_role = serializers.CharField(read_only=True, default=None)
    est_ouvert = serializers.SerializerMethodField()
    prochaine_ouverture = serializers.SerializerMethodField()
    message_statut = serializers.SerializerMethodField()
    fiche = serializers.SerializerMethodField()
    menus_du_jour = serializers.SerializerMethodField()
    menus_en_vigueur_maintenant = serializers.SerializerMethodField()
    carte = serializers.SerializerMethodField()

    def _url(self, champ):
        return _url_absolue(champ, self.context.get('request'))

    def get_logo(self, obj):
        return self._url(obj.logo)

    def get_couverture(self, obj):
        return self._url(obj.photo_couverture)

    def get_latitude(self, obj):
        return obj.localisation.y if obj.localisation else None

    def get_longitude(self, obj):
        return obj.localisation.x if obj.localisation else None

    def get_est_ouvert(self, obj):
        return _statut_de(obj)['est_ouvert']

    def get_prochaine_ouverture(self, obj):
        return _statut_de(obj)['prochaine_ouverture']

    def get_message_statut(self, obj):
        return _statut_de(obj)['message_statut']

    def get_fiche(self, obj):
        f = obj.fiche
        return {
            'telephones': TelephoneRestaurantSerializer(f.telephones.all(), many=True).data,
            'adresse_reperes': f.adresse_reperes,
            'facebook': f.facebook, 'instagram': f.instagram, 'tiktok': f.tiktok,
            'specialites': f.specialites, 'services': f.services,
            'delai_preparation_min': f.delai_preparation_min,
            'horaires': HoraireOuvertureSerializer(
                obj.horaires.order_by('jour_semaine'), many=True).data,
        }

    def get_menus_du_jour(self, obj):
        menus = services.menus_du_jour(obj.fiche)
        return {s: (MenuProgrammeSerializer(m, context=self.context).data if m else None)
               for s, m in menus.items()}

    def get_menus_en_vigueur_maintenant(self, obj):
        menus = services.menus_en_vigueur_maintenant(obj.fiche)
        return {s: MenuProgrammeSerializer(m, context=self.context).data
               for s, m in menus.items()}

    def get_carte(self, obj):
        # sections_menu (actives) et leurs articles sont préchargés par la vue.
        sections = sorted((s for s in obj.sections_menu.all() if s.est_active), key=_cle_tri)
        return SectionCartePubliqueSerializer(sections, many=True, context=self.context).data
