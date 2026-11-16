"""Tests : lien entre une pub reconduite et sa copie (reconduite_depuis).

- partenaire et admin : la copie pointe vers l'original (reconduite_depuis_id) ;
- copie en attente de paiement / de validation / active (non masquée) :
  nouvelle reconduction refusée en 400 (partenaire et admin) ;
- copie terminée, rejetée, brouillon ou masquée par le partenaire : ne bloque pas ;
- double reconduction admin refusée en 400 ;
- champs exposés (reconduite_le, reconduction_id, reconduction_statut,
  peut_etre_reconduite, reconduite_depuis_id) dans mes-publicites,
  admin/stats et mes-stats ; copie la plus récente quel que soit son statut.

Données propres, transaction annulée (rien ne persiste), limitation de débit
désactivée, total OK / KO.
Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_reconduction.py
"""
import uuid
from datetime import timedelta

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.publicites.models import FormulePublicite, Publicite
from apps.users.models import PlanAbonnement, ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
# Limitation de débit DRF désactivée pour ce script : sinon tous les scripts partagent
# le compteur anonyme (60/min, client de test = 127.0.0.1) et la suite complète reçoit des 429.
from unittest import mock as _mock_debit
from rest_framework.views import APIView as _APIViewDebit
_mock_debit.patch.object(_APIViewDebit, 'get_throttles', return_value=[]).start()


class Rollback(Exception):
    pass


NB_OK, KO = 0, []
CHAMPS = {'reconduite_le', 'reconduction_id', 'reconduction_statut', 'peut_etre_reconduite', 'reconduite_depuis_id'}
MESSAGE_BLOQUE = 'déjà été reconduite'


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, detail)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


def utilisateur(role='client', **kw):
    return User.objects.create(telephone=telephone_libre(), username=f't_reco_{uuid.uuid4().hex[:8]}',
                               role=role, est_verifie=True, **kw)


def entetes(user):
    return {'secure': True, 'HTTP_HOST': HOST, 'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}'}


try:
    with transaction.atomic():
        c = Client()
        uid = uuid.uuid4().hex[:6]
        aujourdhui = timezone.localdate()
        plan = PlanAbonnement.objects.get(libelle='Basique')
        p_user = utilisateur('partenaire')
        partenaire = ProfilPartenaire.objects.create(
            user=p_user, plan=plan, nom_commerce=f'Boutique Reco {uid}', type_partenaire='commercant',
            statut='actif', est_visible=True)
        superadmin = utilisateur('admin', is_staff=True, is_superuser=True)
        formule = FormulePublicite.objects.create(nom=f'Formule Reco {uid}', prix=5000, duree_jours=7,
                                                  quota_partenaires=1000, types_affichage=['carrousel'])
        O = Publicite.objects.create(
            partenaire=partenaire, formule=formule, titre=f'Original {uid}', portee='departement',
            image_couverture='publicites/couvertures/reco.jpg', statut='terminee',
            debut_diffusion=timezone.now() - timedelta(days=20), fin_diffusion=timezone.now() - timedelta(days=10))

        def reco_partenaire(pub):
            return c.post(f'/api/v1/publicites/mes-publicites/{pub.id}/reconduire/', {}, **entetes(p_user))

        def reco_admin(pub):
            return c.post(f'/api/v1/publicites/admin/{pub.id}/reconduire/',
                          {'date_debut': str(aujourdhui), 'reglement': 'payee'}, **entetes(superadmin))

        def mes_publicites():
            d = c.get('/api/v1/publicites/mes-publicites/', **entetes(p_user)).json()
            return {x['id']: x for x in (d['results'] if isinstance(d, dict) else d)}

        def statut(pub, valeur, **kw):
            Publicite.objects.filter(pk=pub.pk).update(statut=valeur, **kw)

        print('=== 1. AVANT TOUTE RECONDUCTION ===')
        o = mes_publicites()[str(O.id)]
        ok('mes-publicites : 5 champs presents', CHAMPS <= set(o), set(o))
        ok('original sans copie : peut etre reconduit, champs nuls', (
            o['peut_etre_reconduite'], o['reconduction_id'], o['reconduction_statut'], o['reconduite_le'],
            o['reconduite_depuis_id']) == (True, None, None, None, None), o)

        print('=== 2. RECONDUCTION PARTENAIRE (brouillon) ===')
        r = reco_partenaire(O)
        ok('partenaire -> 201, brouillon', r.status_code == 201 and r.json()['statut'] == 'brouillon', r.content[:200])
        c1 = r.json()
        ok('copie : reconduite_depuis_id = original, ne peut pas etre reconduite (pas terminee)',
           c1['reconduite_depuis_id'] == str(O.id) and c1['peut_etre_reconduite'] is False, c1)
        ok('lien en base', Publicite.objects.get(pk=c1['id']).reconduite_depuis_id == O.id)
        ok('original intact (toujours terminee)', Publicite.objects.get(pk=O.pk).statut == 'terminee')
        o = mes_publicites()[str(O.id)]
        ok('original : copie la plus recente exposee (brouillon), toujours reconductible', (
            o['reconduction_id'], o['reconduction_statut'], o['peut_etre_reconduite']) == (c1['id'], 'brouillon', True)
           and o['reconduite_le'], o)

        print('=== 3. BROUILLON NE BLOQUE PAS ; COPIE LA PLUS RECENTE ===')
        r = reco_partenaire(O)
        ok('2e reconduction avec copie en brouillon -> 201', r.status_code == 201, r.content[:200])
        c2 = Publicite.objects.get(pk=r.json()['id'])
        Publicite.objects.filter(pk=c1['id']).update(cree_le=timezone.now() - timedelta(hours=1))  # ordre net
        ok('reconduction_id = copie la plus recente', mes_publicites()[str(O.id)]['reconduction_id'] == str(c2.id))

        print('=== 4. COPIE QUI BLOQUE ===')
        for valeur in ('en_attente_paiement', 'en_attente_validation', 'active'):
            statut(c2, valeur)
            rp, ra = reco_partenaire(O), reco_admin(O)
            ok(f'copie {valeur} : partenaire -> 400, message clair', rp.status_code == 400
               and MESSAGE_BLOQUE in rp.json()['message'], rp.content[:200])
            ok(f'copie {valeur} : admin -> 400, message clair', ra.status_code == 400
               and MESSAGE_BLOQUE in ra.json()['message'], ra.content[:200])
            o = mes_publicites()[str(O.id)]
            ok(f'copie {valeur} : peut_etre_reconduite false, statut de la copie expose',
               o['peut_etre_reconduite'] is False and o['reconduction_statut'] == valeur, o)
        ok('aucune copie creee pendant les refus', Publicite.objects.filter(reconduite_depuis=O).count() == 2)

        print('=== 5. COPIE QUI NE BLOQUE PAS ===')
        statut(c2, 'active', masquee_par_partenaire=True)
        o = mes_publicites()[str(O.id)]
        ok('copie active MASQUEE par le partenaire : ne bloque pas', o['peut_etre_reconduite'] is True, o)
        statut(c2, 'terminee', masquee_par_partenaire=False)
        ok('copie terminee : ne bloque pas', mes_publicites()[str(O.id)]['peut_etre_reconduite'] is True)
        statut(c2, 'rejetee')
        ok('copie rejetee : ne bloque pas', mes_publicites()[str(O.id)]['peut_etre_reconduite'] is True)
        r = reco_partenaire(O)
        ok('copie rejetee : reconduction partenaire -> 201', r.status_code == 201, r.content[:200])
        Publicite.objects.filter(reconduite_depuis=O, statut='brouillon').update(statut='terminee')

        print('=== 6. RECONDUCTION ADMIN ET DOUBLE RECONDUCTION ===')
        r = reco_admin(O)
        ok('admin -> 201, copie active', r.status_code == 201 and r.json()['statut'] == 'active', r.content[:200])
        d = r.json()
        ok('admin : cle reconduite_depuis conservee + reconduite_depuis_id', d['reconduite_depuis'] == str(O.id)
           and d['reconduite_depuis_id'] == str(O.id) and CHAMPS <= set(d), d)
        c3 = Publicite.objects.get(pk=d['id'])
        ok('lien en base (admin)', c3.reconduite_depuis_id == O.id)
        r2 = reco_admin(O)
        ok('double reconduction admin -> 400', r2.status_code == 400 and MESSAGE_BLOQUE in r2.json()['message'],
           r2.content[:200])
        ok('double reconduction : une seule copie active', Publicite.objects.filter(
            reconduite_depuis=O, statut='active').count() == 1)
        ok('partenaire apres reconduction admin -> 400', reco_partenaire(O).status_code == 400)
        ok('pub non terminee : regle existante inchangee', 'Seule une publicité terminée' in
           reco_admin(c3).json().get('message', ''))

        print('=== 7. ADMIN/STATS ET MES-STATS ===')
        r = c.get('/api/v1/publicites/admin/stats/', **entetes(superadmin))
        lignes = {x['id']: x for x in r.json()['publicites']}
        o, l3 = lignes.get(str(O.id), {}), lignes.get(str(c3.id), {})
        ok('admin/stats : original -> copie active, non reconductible', (
            o.get('reconduction_id'), o.get('reconduction_statut'), o.get('peut_etre_reconduite')) == (
            str(c3.id), 'active', False) and o.get('reconduite_le'), o)
        ok('admin/stats : copie -> reconduite_depuis_id', l3.get('reconduite_depuis_id') == str(O.id)
           and CHAMPS <= set(l3), l3)
        r = c.get('/api/v1/publicites/mes-stats/', **entetes(p_user))
        d = r.json()
        lignes = {x['id']: x for x in (d.get('publicites', d) if isinstance(d, dict) else d)}
        o = lignes.get(str(O.id), {})
        ok('mes-stats : champs de reconduction', CHAMPS <= set(o) and o['reconduction_id'] == str(c3.id)
           and o['peut_etre_reconduite'] is False, o)
        ok('mes-stats : toutes les lignes ont les champs', all(CHAMPS <= set(x) for x in lignes.values()))
        statut(c3, 'terminee')
        ok('copie terminee -> original de nouveau reconductible (admin/stats)', {
            x['id']: x for x in c.get('/api/v1/publicites/admin/stats/', **entetes(superadmin)).json()['publicites']
        }[str(O.id)]['peut_etre_reconduite'] is True)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
