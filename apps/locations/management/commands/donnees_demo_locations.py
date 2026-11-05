"""Données de démonstration des locations (Ferké) : 2 hôtels, 2 résidences
meublées, 2 loueurs de voitures, avec hébergements, véhicules et photos.

    python manage.py donnees_demo_locations                  # crée / complète
    python manage.py donnees_demo_locations --simulation     # tout est annulé à la fin
    python manage.py donnees_demo_locations --sans-images
    python manage.py donnees_demo_locations --supprimer [--simulation] [--avec-reservations]

Idempotente : un partenaire de démo déjà présent (même nom, marqueur [DEMO]
dans sa description, numéro de test) est réutilisé ; un hébergement ou un
véhicule déjà présent (même nom) n'est pas recréé ; seules les photos
manquantes sont ajoutées.

Passe par les serializers existants : CreerPartenaireParAdminSerializer
(compte + profil actif et visible + numéro vérifié + catégories),
EtablissementGestionSerializer, HebergementGestionSerializer,
VehiculeGestionSerializer, ArticleImageImbriqueeSerializer (quota du plan).
Les images passent par ImagesOptimiseesMixin (redimensionnement/compression).

Photos : Pexels uniquement (licence Pexels : usage commercial autorisé,
attribution non obligatoire), choisies sans visage reconnaissable ni logo de
marque en gros plan. L'URL source de chaque photo est affichée au rapport.
"""
import urllib.error
import urllib.request
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError
from rest_framework.exceptions import ValidationError

from apps.catalog.models import ArticleImage, Article, Categorie, PartenaireCategorie
from apps.catalog.serializers import ArticleImageImbriqueeSerializer
from apps.core.exceptions import ErreurMetier
from apps.geo.models import Departement, Localite, Quartier
from apps.locations import services
from apps.locations.serializers import (
    EtablissementGestionSerializer, HebergementGestionSerializer, VehiculeGestionSerializer,
)
from apps.users.models import NumeroVerifie, PlanAbonnement, ProfilPartenaire, User
from apps.users.serializers import CreerPartenaireParAdminSerializer

MARQUEUR = '[DEMO]'
PREFIXE_TELEPHONE = '+22507020001'  # + 2 chiffres : +2250702000100 … +2250702000199
PIN_DEMO = '0000'
PLAN_DEMO = 'premium'  # 10 photos par article : le Basique (1 photo) bloquerait les galeries
ACTEUR = {'acteur_role': 'admin', 'acteur_nom': 'Données de démo'}
USER_AGENT = 'poufiret-donnees-demo/1.0'


def pexels(photo_id):
    """(URL de téléchargement, URL de la page source) d'une photo Pexels."""
    return (f'https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg'
            f'?auto=compress&cs=tinysrgb&w=1600',
            f'https://www.pexels.com/photo/{photo_id}/')


# ═══════════════════════════════════════════════════════════════════════
# Données
# ═══════════════════════════════════════════════════════════════════════

EQUIP_CHAMBRE = ['climatisation', 'tv', 'wifi', 'eau_chaude']
EQUIP_SUITE = EQUIP_CHAMBRE + ['minibar', 'coffre', 'balcon', 'refrigerateur']
EQUIP_STUDIO = EQUIP_CHAMBRE + ['cuisine', 'refrigerateur']

CONDITIONS_HOTEL = 'Pièce d\'identité exigée à l\'arrivée. Paiement à l\'arrivée.'
ANNULATION = 'Annulation gratuite jusqu\'à 24 h avant l\'arrivée.'


def _hotel(etoiles, equipements):
    return {'type_etablissement': 'hotel', 'etoiles': etoiles,
            'heure_arrivee': '14:00', 'heure_depart': '12:00',
            'equipements_etablissement': equipements,
            'petit_dejeuner': 'en_option', 'prix_petit_dejeuner': 2000,
            'politique_annulation': ANNULATION, 'conditions': CONDITIONS_HOTEL}


def _residence(equipements):
    return {'type_etablissement': 'residence_meublee', 'etoiles': None,
            'heure_arrivee': '14:00', 'heure_depart': '12:00',
            'equipements_etablissement': equipements, 'petit_dejeuner': 'non',
            'prix_petit_dejeuner': None, 'politique_annulation': ANNULATION,
            'conditions': CONDITIONS_HOTEL + ' Caution de 50 000 F pour un séjour au mois.'}


def _chambres(unites, photos):
    """Chambre simple / double / suite d'un hôtel. photos : 3 listes d'ids."""
    simple, double, suite = unites
    return [
        {'nom': 'Chambre simple', 'type_hebergement': 'chambre_simple', 'prix': 15000,
         'capacite_adultes': 1, 'capacite_enfants': 0, 'lits': '1 lit 120 cm', 'surface_m2': 14,
         'equipements_hebergement': EQUIP_CHAMBRE, 'nb_unites': simple, 'photos': photos[0],
         'description': 'Chambre climatisée pour une personne, salle d\'eau privative.'},
        {'nom': 'Chambre double', 'type_hebergement': 'chambre_double', 'prix': 25000,
         'capacite_adultes': 2, 'capacite_enfants': 1, 'lits': '1 lit 160 cm', 'surface_m2': 20,
         'equipements_hebergement': EQUIP_CHAMBRE + ['minibar'], 'nb_unites': double,
         'photos': photos[1],
         'description': 'Chambre climatisée pour deux personnes, salle de bain privative.'},
        {'nom': 'Suite', 'type_hebergement': 'suite', 'prix': 45000,
         'capacite_adultes': 2, 'capacite_enfants': 2, 'lits': '1 lit 200 cm + canapé',
         'surface_m2': 40, 'equipements_hebergement': EQUIP_SUITE, 'nb_unites': suite,
         'photos': photos[2],
         'description': 'Suite avec coin salon, balcon et grande salle de bain.'},
    ]


def _logements(unites, photos):
    """Studio / appartement 2 pièces d'une résidence meublée."""
    studio, appart = unites
    return [
        {'nom': 'Studio meublé', 'type_hebergement': 'studio', 'prix': 20000,
         'prix_semaine': 120000, 'prix_mois': 400000,
         'capacite_adultes': 2, 'capacite_enfants': 1, 'lits': '1 lit 160 cm', 'surface_m2': 30,
         'equipements_hebergement': EQUIP_STUDIO, 'nb_unites': studio, 'photos': photos[0],
         'description': 'Studio meublé avec coin cuisine équipé, idéal pour un séjour long.'},
        {'nom': 'Appartement 2 pièces', 'type_hebergement': 'appartement', 'prix': 35000,
         'prix_semaine': 210000, 'prix_mois': 700000,
         'capacite_adultes': 2, 'capacite_enfants': 2, 'lits': '1 lit 160 cm + canapé-lit',
         'surface_m2': 55, 'equipements_hebergement': EQUIP_STUDIO + ['balcon'],
         'nb_unites': appart, 'photos': photos[1],
         'description': 'Chambre, salon et cuisine équipée : un vrai appartement, au mois ou à la nuit.'},
    ]


def _vehicules(photos):
    berline, quatre_quatre, minibus = photos
    commun = {'climatisation': True, 'carburant_inclus': False, 'duree_min_jours': 1,
              'zone_circulation': 'Ferké et environs'}
    return [
        {**commun, 'nom': 'Toyota Corolla', 'categorie_vehicule': 'voiture',
         'marque': 'Toyota', 'modele': 'Corolla', 'annee': 2019, 'couleur': 'Blanc',
         'nb_places': 5, 'boite': 'automatique', 'carburant': 'essence',
         'equipements': ['bluetooth', 'usb'], 'prix': 25000,
         'chauffeur_disponible': False, 'caution': 100000,
         'km_inclus_par_jour': 200, 'prix_km_supplementaire': 150, 'photos': berline,
         'description': 'Berline confortable et économique, idéale en ville.'},
        {**commun, 'nom': 'Toyota Prado 4x4', 'categorie_vehicule': 'suv_4x4',
         'marque': 'Toyota', 'modele': 'Land Cruiser Prado', 'annee': 2018, 'couleur': 'Gris',
         'nb_places': 7, 'boite': 'automatique', 'carburant': 'diesel',
         'equipements': ['gps', 'bluetooth', 'camera_recul'], 'prix': 45000,
         'chauffeur_disponible': True, 'prix_jour_avec_chauffeur': 55000, 'caution': 200000,
         'km_inclus_par_jour': 250, 'prix_km_supplementaire': 200, 'photos': quatre_quatre,
         'description': '4x4 robuste pour les pistes ; chauffeur disponible en option.'},
        {**commun, 'nom': 'Minibus Toyota Hiace', 'categorie_vehicule': 'minibus',
         'marque': 'Toyota', 'modele': 'Hiace', 'annee': 2017, 'couleur': 'Blanc',
         'nb_places': 15, 'boite': 'manuelle', 'carburant': 'diesel',
         'equipements': ['usb'], 'prix': 60000,
         'chauffeur_disponible': True, 'chauffeur_obligatoire': True,
         'prix_jour_avec_chauffeur': 60000, 'caution': 150000,
         'km_inclus_par_jour': 300, 'prix_km_supplementaire': 200, 'photos': minibus,
         'description': 'Minibus 15 places pour groupes et cérémonies, chauffeur inclus.'},
    ]


# Photos Pexels vérifiées une à une (contenu, pas de visage, pas de gros logo).
PARTENAIRES = [
    {'nom': 'Hôtel Le Tchologo', 'type': 'hotelier', 'quartier': 'Résidentiel',
     'secteur': 'Route de Korhogo', 'gps': (9.5962, -5.1931),
     'description': 'Hôtel 3 étoiles au calme du quartier Résidentiel : piscine, restaurant, '
                    'salle de conférence.',
     'etablissement': _hotel(3, ['wifi', 'parking', 'piscine', 'restaurant', 'bar',
                                 'salle_conference', 'groupe_electrogene', 'securite_24h']),
     'logo': 10047588, 'couverture': 17619969,
     'hebergements': _chambres((5, 4, 2), [
         [9899861, 5629141, 17264519],      # simple : chambre, douche, salon de l'hôtel
         [34672504, 16113326, 14387344],    # double : chambre, salle de bain, piscine
         [18285946, 18285941, 16113326],    # suite : chambre, chambre, salle de bain
     ])},
    {'nom': 'Hôtel La Savane', 'type': 'hotelier', 'quartier': 'Gare',
     'secteur': 'Près de la gare', 'gps': (9.5893, -5.1985),
     'description': 'Hôtel 2 étoiles proche de la gare, accueil chaleureux et piscine.',
     'etablissement': _hotel(2, ['wifi', 'parking', 'piscine', 'restaurant',
                                 'groupe_electrogene', 'securite_24h']),
     'logo': 28700692, 'couverture': 2587054,
     'hebergements': _chambres((4, 3, 2), [
         [13871317, 7534571, 18426842],     # simple : chambre, salle de bain, salon
         [5461582, 8082195, 7974837],       # double : chambre, salle de bain, piscine
         [14547145, 18254581, 26886815],    # suite : chambre, coin repos, salle de bain
     ])},
    {'nom': 'Résidence Kafigué', 'type': 'hotelier', 'quartier': 'Kafalovogo',
     'secteur': '', 'gps': (9.6005, -5.2010),
     'description': 'Résidence meublée : studios et appartements équipés, à la nuit, '
                    'à la semaine ou au mois.',
     'etablissement': _residence(['wifi', 'parking', 'groupe_electrogene', 'securite_24h']),
     'logo': 30151768, 'couverture': 30151768, 'sous_categorie': 'Résidences meublées',
     'hebergements': _logements((3, 2), [
         [8082559, 6447393, 7031571],       # studio : séjour, studio, salle de bain
         [6588599, 7535076, 6312076],       # appartement : salon, cuisine, séjour
     ])},
    {'nom': 'Résidence Les Palmiers', 'type': 'hotelier', 'quartier': 'Lanviara',
     'secteur': '', 'gps': (9.5870, -5.1902),
     'description': 'Résidence meublée avec piscine, appartements spacieux et sécurisés.',
     'etablissement': _residence(['wifi', 'parking', 'piscine', 'groupe_electrogene',
                                  'securite_24h', 'blanchisserie']),
     'logo': 28700692, 'couverture': 15994062, 'sous_categorie': 'Résidences meublées',
     'hebergements': _logements((4, 2), [
         [6492402, 7040696, 15994062],      # studio : séjour, cuisine, piscine
         [6933852, 7031214, 6527037],       # appartement : séjour, cuisine, salon
     ])},
    {'nom': 'Ferké Auto Location', 'type': 'loueur_voiture', 'quartier': 'Douane',
     'secteur': 'Axe Abidjan - Ouaga', 'gps': (9.5920, -5.1960),
     'description': 'Location de voitures, 4x4 et minibus, avec ou sans chauffeur.',
     'logo': 9544521, 'couverture': 28836717,
     'vehicules': _vehicules([
         [9544521, 28836717, 8687569],      # berline
         [12992198, 18207344],              # 4x4
         [31374505, 12474180, 12821568],    # minibus
     ])},
    {'nom': 'Tchologo Cars', 'type': 'loueur_voiture', 'quartier': 'Dioulabougou',
     'secteur': 'Près du marché', 'gps': (9.5948, -5.2003),
     'description': 'Véhicules récents et entretenus pour vos déplacements dans le Tchologo.',
     'logo': 31374505, 'couverture': 12992198,
     'vehicules': _vehicules([
         [28836717, 9544521, 8687599],
         [18207344, 12992198],
         [12474180, 31374505, 13731636],
     ])},
]


class _Simulation(Exception):
    """Annule la transaction en mode --simulation."""


# ═══════════════════════════════════════════════════════════════════════
# Commande
# ═══════════════════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = 'Crée (ou supprime avec --supprimer) les données de démonstration des locations à Ferké.'

    def add_arguments(self, parser):
        parser.add_argument('--supprimer', action='store_true',
                            help='Supprime tout ce que la commande a créé (marqueur [DEMO]).')
        parser.add_argument('--simulation', action='store_true',
                            help='Exécute tout dans une transaction annulée à la fin ; '
                                 'les photos sont seulement vérifiées, pas téléchargées.')
        parser.add_argument('--sans-images', action='store_true', help='N\'ajoute aucune photo.')
        parser.add_argument('--avec-reservations', action='store_true',
                            help='Avec --supprimer : supprime aussi les demandes de réservation '
                                 'faites sur les partenaires de démo (sinon elles bloquent).')

    def handle(self, *args, **opts):
        self.simulation = opts['simulation']
        self.images_actives = not opts['sans_images']
        self.sources = []          # (contexte, page source) pour le rapport
        self.cache = {}            # photo_id -> octets (une photo réutilisée = un téléchargement)
        if self.simulation:
            self.stdout.write(self.style.WARNING('MODE SIMULATION : rien ne sera enregistré.'))
        try:
            with transaction.atomic():
                if opts['supprimer']:
                    self._supprimer(opts['avec_reservations'])
                else:
                    self._creer()
                if self.simulation:
                    raise _Simulation
        except _Simulation:
            self.stdout.write(self.style.WARNING('Simulation terminée : transaction annulée.'))

    # ── Création ──────────────────────────────────────────────────────

    def _creer(self):
        departement = Departement.objects.filter(nom='Ferké').first()
        localite = Localite.objects.filter(departement=departement, nom='Ferké', est_actif=True).first()
        if departement is None or localite is None:
            raise CommandError('Département ou localité « Ferké » introuvable.')
        plan = PlanAbonnement.objects.filter(code=PLAN_DEMO).first()
        if plan is None:
            raise CommandError(f'Plan « {PLAN_DEMO} » introuvable.')

        lignes = []
        for donnees in PARTENAIRES:
            partenaire, cree = self._partenaire(donnees, departement, localite, plan)
            if donnees['type'] == 'hotelier':
                self._etablissement(partenaire, donnees)
                nb = sum(self._hebergement(partenaire, h) for h in donnees['hebergements'])
            else:
                nb = sum(self._vehicule(partenaire, v) for v in donnees['vehicules'])
            lignes.append((partenaire, cree, nb))

        self.stdout.write('\n=== Partenaires de démo ===')
        for p, cree, nb in lignes:
            etat = 'créé' if cree else 'déjà présent'
            self.stdout.write(f'  #{p.id:<5} {p.nom_commerce:<26} {p.get_type_partenaire_display():<18} '
                              f'{p.user.telephone}  PIN {PIN_DEMO}  ({etat}, {nb} bien(s) ajouté(s))')
        if self.sources:
            self.stdout.write('\n=== Sources des photos (Pexels) ===')
            for contexte, page in self.sources:
                self.stdout.write(f'  {contexte:<55} {page}')

    def _partenaire(self, d, departement, localite, plan):
        """Partenaire de démo existant, ou créé via le serializer de création admin."""
        existant = ProfilPartenaire.objects.filter(
            nom_commerce=d['nom'], description__contains=MARQUEUR,
            user__telephone__startswith=PREFIXE_TELEPHONE).select_related('user').first()
        if existant:
            if self.images_actives and not existant.logo:
                self._logo_couverture(existant, d)
            return existant, False

        quartier = (Quartier.objects.filter(localite=localite, nom=d['quartier'], est_actif=True).first()
                    or Quartier.objects.filter(localite=localite, est_actif=True).order_by('id').first())
        telephone = self._numero_libre()
        lat, lng = d['gps']
        ser = CreerPartenaireParAdminSerializer(data={
            'telephone': telephone, 'type_partenaire': d['type'], 'nom_commerce': d['nom'],
            'description': f"{d['description']}\n{MARQUEUR} Données de démonstration.",
            'secteur': d['secteur'], 'adresse': f"{quartier.nom}, Ferké",
            'departement': departement.id, 'localite_id': localite.id, 'quartier_id': quartier.id,
            'latitude': lat, 'longitude': lng,
            'telephone_pro': telephone, 'whatsapp': telephone, 'plan_id': plan.id,
        })
        if not ser.is_valid():
            raise CommandError(f"{d['nom']} : {ser.errors}")
        profil = ser.save()

        # PIN de démo fixe (le serializer en tire un aléatoire) et pas d'écran
        # « change ton PIN » : sinon le premier testeur le modifie pour tout le monde.
        user = profil.user
        user.set_password(PIN_DEMO)
        user.pin_par_defaut = False
        user.save(update_fields=['password', 'pin_par_defaut'])

        if d.get('sous_categorie'):
            self._sous_categorie(profil, d['sous_categorie'])
        if self.images_actives:
            self._logo_couverture(profil, d)
        return profil, True

    def _numero_libre(self):
        for i in range(100):
            tel = f'{PREFIXE_TELEPHONE}{i:02d}'
            if not User.objects.filter(telephone=tel).exists() and \
                    not NumeroVerifie.objects.filter(telephone=tel).exists():
                return tel
        raise CommandError(f'Aucun numéro libre dans {PREFIXE_TELEPHONE}00-99.')

    def _sous_categorie(self, profil, nom):
        categorie = Categorie.objects.filter(nom__iexact=nom, est_active=True, est_archivee=False).first()
        if categorie is None:
            self.stdout.write(self.style.WARNING(
                f'  Sous-catégorie « {nom} » absente : {profil.nom_commerce} reste dans '
                f'sa catégorie par défaut.'))
            return
        PartenaireCategorie.objects.get_or_create(
            partenaire=profil, categorie=categorie, defaults={'est_principale': False})

    def _etablissement(self, partenaire, d):
        fiche = services.fiche_etablissement(partenaire, creer=True)
        ser = EtablissementGestionSerializer(fiche, data=d['etablissement'], partial=True, context=ACTEUR)
        if not ser.is_valid():
            raise CommandError(f"{d['nom']} (fiche établissement) : {ser.errors}")
        ser.save()

    def _bien(self, partenaire, d, serializer_classe, article_type):
        """Crée un hébergement / véhicule s'il n'existe pas ; ajoute ses photos
        manquantes. Retourne 1 si créé, 0 sinon."""
        donnees = {k: v for k, v in d.items() if k != 'photos'}
        donnees['description'] = f"{d['description']}\n{MARQUEUR}"
        article = Article.objects.filter(partenaire=partenaire, nom=d['nom'], type=article_type).first()
        cree = 0
        if article is None:
            if serializer_classe is VehiculeGestionSerializer:
                # Point de prise en charge = l'agence (localisation du partenaire).
                pos = partenaire.localisation
                donnees.update({'localite_id': partenaire.localite_id,
                                'quartier_id': partenaire.quartier_geo_id,
                                'secteur': partenaire.secteur,
                                'latitude': pos.y if pos else None,
                                'longitude': pos.x if pos else None})
            ser = serializer_classe(data=donnees, context={'partenaire': partenaire, **ACTEUR})
            if not ser.is_valid():
                raise CommandError(f"{partenaire.nom_commerce} / {d['nom']} : {ser.errors}")
            article = ser.save().article
            cree = 1
        if self.images_actives and not article.images.exists():
            self._photos_article(article, d['photos'], f"{partenaire.nom_commerce} / {d['nom']}")
        return cree

    def _hebergement(self, partenaire, d):
        return self._bien(partenaire, d, HebergementGestionSerializer, Article.Type.HEBERGEMENT)

    def _vehicule(self, partenaire, d):
        return self._bien(partenaire, d, VehiculeGestionSerializer, Article.Type.VEHICULE)

    # ── Photos ────────────────────────────────────────────────────────

    def _telecharger(self, photo_id):
        """Octets de la photo (None si indisponible). En simulation : vérifie
        seulement que l'URL répond. Coupe les images au premier échec réseau."""
        url, _page = pexels(photo_id)
        if photo_id in self.cache:
            return self.cache[photo_id]
        try:
            requete = urllib.request.Request(
                url, headers={'User-Agent': USER_AGENT}, method='HEAD' if self.simulation else 'GET')
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                contenu = b'' if self.simulation else reponse.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError):
                self.stdout.write(self.style.WARNING(f'  Photo {photo_id} indisponible ({e.code}), ignorée.'))
                return None
            self.stdout.write(self.style.WARNING(
                f'  Pexels inaccessible depuis le serveur ({e}) : poursuite SANS images.'))
            self.images_actives = False
            return None
        self.cache[photo_id] = contenu
        return contenu

    def _photos_article(self, article, ids, contexte):
        for ordre, photo_id in enumerate(ids):
            contenu = self._telecharger(photo_id)
            if contenu is None:
                if not self.images_actives:
                    return
                continue
            self.sources.append((f'{contexte} (photo {ordre + 1})', pexels(photo_id)[1]))
            if self.simulation:
                continue
            fichier = SimpleUploadedFile(f'{article.slug}-{ordre + 1}.jpg', contenu,
                                         content_type='image/jpeg')
            ser = ArticleImageImbriqueeSerializer(
                data={'image': fichier, 'legende': article.nom, 'ordre': ordre,
                      'est_principale': ordre == 0},
                context={'article': article})
            try:
                ser.is_valid(raise_exception=True)
            except (ErreurMetier, ValidationError) as e:  # quota du plan, image refusée
                self.stdout.write(self.style.WARNING(f'  {contexte} : photo ignorée ({e.detail})'))
                continue
            ser.save(article=article, est_active=True)

    def _logo_couverture(self, profil, d):
        """Logo (photo recadrée en carré) et couverture. Affectés comme fichiers
        non enregistrés : ImagesOptimiseesMixin les optimise au save()."""
        from PIL import Image, ImageOps
        champs = []
        for champ, photo_id in (('logo', d['logo']), ('photo_couverture', d['couverture'])):
            contenu = self._telecharger(photo_id)
            if contenu is None:
                if not self.images_actives:
                    return
                continue
            self.sources.append((f"{profil.nom_commerce} ({champ})", pexels(photo_id)[1]))
            if self.simulation:
                continue
            if champ == 'logo':
                tampon = BytesIO()
                ImageOps.fit(Image.open(BytesIO(contenu)).convert('RGB'), (600, 600)).save(
                    tampon, format='JPEG', quality=90)
                contenu = tampon.getvalue()
            setattr(profil, champ, ContentFile(contenu, name=f'demo-{profil.id}-{champ}.jpg'))
            champs.append(champ)
        if champs:
            profil.save(update_fields=champs + ['updated_at'])

    # ── Suppression ───────────────────────────────────────────────────

    def _supprimer(self, avec_reservations):
        partenaires = list(ProfilPartenaire.objects.filter(
            description__contains=MARQUEUR, user__telephone__startswith=PREFIXE_TELEPHONE,
        ).select_related('user'))
        if not partenaires:
            self.stdout.write('Aucune donnée de démo à supprimer.')
            return

        fichiers = list(ArticleImage.objects.filter(article__partenaire__in=partenaires)
                        .values_list('image', flat=True))
        for p in partenaires:
            fichiers += [f.name for f in (p.logo, p.photo_couverture) if f]

        if avec_reservations:
            from apps.reservations.models import DemandeReservation
            nb, _ = DemandeReservation.objects.filter(partenaire__in=partenaires).delete()
            self.stdout.write(f'  {nb} ligne(s) de réservation de démo supprimée(s).')

        telephones = [p.user.telephone for p in partenaires]
        for p, telephone in zip(partenaires, telephones):
            pk = p.pk
            try:
                p.user.delete()  # cascade : profil, fiche, articles, fiches, images, catégories
            except ProtectedError as e:
                raise CommandError(
                    f'{p.nom_commerce} : suppression bloquée par des données liées '
                    f'({len(e.protected_objects)} objet(s), ex. réservations). '
                    f'Relancez avec --avec-reservations. Rien n\'a été supprimé.')
            self.stdout.write(f'  Supprimé : #{pk} {p.nom_commerce} ({telephone})')
        NumeroVerifie.objects.filter(telephone__in=telephones).delete()

        # Les fichiers ne sont effacés du disque qu'une fois la suppression validée.
        def effacer():
            for nom in fichiers:
                if nom and default_storage.exists(nom):
                    default_storage.delete(nom)
        transaction.on_commit(effacer)
        self.stdout.write(f'{len(partenaires)} partenaire(s) de démo supprimé(s), '
                          f'{len(fichiers)} fichier(s) image à effacer.')
