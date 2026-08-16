"""Seed de tests Poufiret — partenaires, pubs, clients pour tester les portees.
Idempotent : reexecutable sans doublons (get_or_create sur cles naturelles).
"""
import io
from datetime import timedelta
from django.utils import timezone
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.geo.models import Departement
from apps.catalog.models import Categorie, PartenaireCategorie
from apps.users.models import PlanAbonnement, ProfilPartenaire
from apps.publicites.models import FormulePublicite, Publicite, Portee

User = get_user_model()

def png_placeholder():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), (200, 200, 200)).save(buf, format='PNG')
    return buf.getvalue()

PNG = png_placeholder()

def dep(nom):
    return Departement.objects.get(nom=nom)

def cat(nom_contient):
    return Categorie.objects.filter(nom__icontains=nom_contient).first()

plan_basique  = PlanAbonnement.objects.get(code='basique')
plan_standard = PlanAbonnement.objects.get(code='standard')
plan_premium  = PlanAbonnement.objects.get(code='premium')
plan_vip      = PlanAbonnement.objects.get(code='vip')
PLANS = {'basique': plan_basique, 'standard': plan_standard,
         'premium': plan_premium, 'vip': plan_vip}

auj = timezone.now().date()
fin_ab = auj + timedelta(days=30)

PARTENAIRES = [
    ('101', 'Resto Ferke Centre',   'Restaurants',   'Ferké',          'basique',  'restaurateur'),
    ('102', 'Pharma Ferke',         'Pharmacie',     'Ferké',          'standard', 'pharmacien'),
    ('103', 'Boulangerie Ferke',    'Boulangerie',   'Ferké',          'premium',  'boulanger'),
    ('104', 'Coiffure Ferke VIP',   'Coiffure',      'Ferké',          'vip',      'coiffeur'),
    ('105', 'Plomberie Ferke',      'Plomberie',     'Ferké',          'basique',  'plombier'),
    ('106', 'Resto Kong',           'Restaurants',   'Kong',           'standard', 'restaurateur'),
    ('107', 'Boutique Kong',        'Boutiques',     'Kong',           'premium',  'commercant'),
    ('108', 'Resto Ouangolo',       'Restaurants',   'Ouangolodougou', 'basique',  'restaurateur'),
    ('109', 'Hotel Ouangolo VIP',   'Hôtels',        'Ouangolodougou', 'vip',      'hotelier'),
    ('110', 'Resto Korhogo',        'Restaurants',   'Korhogo',        'standard', 'restaurateur'),
    ('111', 'Couture Korhogo',      'Couture',       'Korhogo',        'premium',  'couturier'),
    ('112', 'Meca Korhogo VIP',     'Mécanique auto','Korhogo',        'vip',      'mecanicien'),
    ('113', 'Resto Sinematiali',    'Restaurants',   'Sinématiali',    'basique',  'restaurateur'),
    ('114', 'Resto Boundiali',      'Restaurants',   'Boundiali',      'standard', 'restaurateur'),
    ('115', 'Librairie Boundiali',  'Librairie',     'Boundiali',      'premium',  'libraire'),
]

profils = {}
with transaction.atomic():
    for suf, enseigne, cat_nom, dep_nom, plan_code, type_p in PARTENAIRES:
        tel = f'0701000{suf}'
        user, cree = User.objects.get_or_create(
            telephone=tel,
            defaults={'username': tel, 'role': User.Role.PARTENAIRE,
                      'est_verifie': True, 'pin_par_defaut': True},
        )
        if cree:
            user.set_password('0000')
            user.save()
        profil, _ = ProfilPartenaire.objects.get_or_create(
            user=user,
            defaults={
                'type_partenaire': type_p, 'nom_commerce': enseigne,
                'description': f'Partenaire de test — {enseigne}',
                'ville': dep_nom, 'departement': dep(dep_nom),
                'telephone_pro': tel, 'plan': PLANS[plan_code],
                'abonnement_debut': auj,
                'abonnement_fin': None if plan_code == 'basique' else fin_ab,
                'statut': ProfilPartenaire.Statut.ACTIF, 'est_visible': True,
                'source_inscription': ProfilPartenaire.SourceInscription.ADMIN,
            },
        )
        if not profil.logo:
            profil.logo.save(f'logo_{suf}.png', ContentFile(PNG), save=True)
        categorie = cat(cat_nom)
        if categorie:
            PartenaireCategorie.objects.get_or_create(
                partenaire=profil, categorie=categorie,
                defaults={'est_principale': True})
        profils[enseigne] = profil

print(f'OK {len(profils)} partenaires prets')

formule = FormulePublicite.objects.get(nom='Découverte')
debut = timezone.now() - timedelta(hours=1)
fin = timezone.now() + timedelta(days=30)
PUBS = [
    ('Resto Ferke Centre', Portee.DEPARTEMENT, 'departement'),
    ('Plomberie Ferke',    Portee.DISTRICT,    'district'),
    ('Boulangerie Ferke',  Portee.DEPARTEMENT, 'region'),
    ('Coiffure Ferke VIP', Portee.REGION,      'district'),
    ('Resto Kong',         Portee.REGION,      'region'),
]
nb_pubs = 0
with transaction.atomic():
    for enseigne, portee_achetee, attendue in PUBS:
        profil = profils[enseigne]
        pub, cree = Publicite.objects.get_or_create(
            partenaire=profil, titre=f'Promo test — {enseigne}',
            defaults={'formule': formule,
                      'description': f'Campagne de test pour {enseigne}',
                      'portee': portee_achetee,
                      'statut': Publicite.Statut.ACTIVE,
                      'debut_diffusion': debut, 'fin_diffusion': fin},
        )
        if cree and not pub.image_couverture:
            pub.image_couverture.save(f'pub_{enseigne[:6]}.png',
                                      ContentFile(PNG), save=True)
        eff = pub.portee_effective
        flag = 'OK' if eff == attendue else 'ERREUR attendu ' + attendue
        print(f'  Pub {enseigne:22} achetee={portee_achetee:11} -> effective={eff:11} {flag}')
        nb_pubs += 1
print(f'OK {nb_pubs} publicites pretes')

CLIENTS = [
    ('001', 'Ferké'), ('002', 'Kong'), ('003', 'Ouangolodougou'),
    ('004', 'Korhogo'), ('005', 'Sinématiali'), ('006', 'Boundiali'),
]
nb_clients = 0
with transaction.atomic():
    for suf, dep_nom in CLIENTS:
        tel = f'0701000{suf}'
        user, cree = User.objects.get_or_create(
            telephone=tel,
            defaults={'username': tel, 'role': User.Role.CLIENT,
                      'est_verifie': True, 'pin_par_defaut': True,
                      'departement': dep(dep_nom)},
        )
        if cree:
            user.set_password('0000')
            user.save()
        nb_clients += 1
print(f'OK {nb_clients} clients prets')
print('IDENTIFIANTS (PIN 0000) : clients 0701000001-006, partenaires 0701000101-115')
