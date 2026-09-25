"""Tests : CRUD admin des formules pub, paramètres généraux, capacité
gerer_formules_pub, journal, anti-escalade.

Execution (tout est annule a la fin) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_formules_admin.py
"""
import json

from django.db import transaction
from django.test import Client
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.administration.views import _filtrer_anti_escalade
from apps.publicites.models import FormulePublicite, ParametresPublicite, Publicite
from apps.publicites.services import appliquer_transition
from apps.users.models import ProfilPartenaire, User

HOST = 'poufiret.tenelo.cloud'
NB = 0


class Rollback(Exception):
    pass


def ok(libelle, cond, detail=''):
    global NB
    print(('OK   ' if cond else 'FAIL '), libelle, '' if cond else detail)
    assert cond, f'{libelle} {detail}'
    NB += 1


def h(user):
    return {'HTTP_AUTHORIZATION': f'Bearer {AccessToken.for_user(user)}', 'HTTP_HOST': HOST}


def resultats(r):
    """Deballe l'enveloppe de pagination DRF ({count,next,previous,results})
    si presente, sinon retourne la reponse telle quelle (liste brute)."""
    data = r.json()
    return data['results'] if isinstance(data, dict) and 'results' in data else data


def j(url, method, user, corps=None):
    c = Client()
    fn = getattr(c, method)
    kw = {'secure': True, **h(user)}
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


GESTION = '/api/v1/publicites/admin/formules/gestion/'
PARAMS = '/api/v1/publicites/admin/parametres/'

avant_f = FormulePublicite.objects.count()
avant_p = Publicite.objects.count()
try:
    with transaction.atomic():
        superadmin = User.objects.filter(is_superuser=True).first()
        admin_sans = User.objects.create(
            telephone='+22502000001', username='t_sans_formules', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_sans.set_password('0000'); admin_sans.save()
        PermissionsAdmin.objects.create(admin=admin_sans)
        admin_avec = User.objects.create(
            telephone='+22502000002', username='t_avec_formules', role=User.Role.ADMIN,
            is_staff=True, is_superuser=False, est_verifie=True)
        admin_avec.set_password('0000'); admin_avec.save()
        PermissionsAdmin.objects.create(admin=admin_avec, gerer_formules_pub=True)
        pa = ProfilPartenaire.objects.get(id=2)

        print('\n=== 0. CAPACITE + ANTI-ESCALADE ===')
        ok('nouvelle capacite existe sur PermissionsAdmin',
           hasattr(admin_avec.permissions_admin, 'gerer_formules_pub'))
        filtre = _filtrer_anti_escalade({'gerer_formules_pub': True, 'voir_stats': True}, admin_avec)
        ok('anti-escalade : non-superadmin ne peut pas accorder gerer_formules_pub',
           'gerer_formules_pub' not in filtre and 'voir_stats' in filtre, filtre)
        filtre_sa = _filtrer_anti_escalade({'gerer_formules_pub': True}, superadmin)
        ok('superadmin peut accorder gerer_formules_pub', filtre_sa.get('gerer_formules_pub') is True)

        print('\n=== 1. CRUD : super-admin OK, sans capacite 403, avec capacite OK ===')
        corps_base = dict(
            nom='Formule Test QA', prix=5000, priorite=1, duree_jours=7,
            passages_par_jour=4, duree_affichage_secondes=6, quota_partenaires=5,
            types_affichage=['carrousel', 'bandeau_bas'], nb_images_max=2,
            video_autorisee=False,
        )
        r = j(GESTION, 'get', admin_sans)
        ok('admin sans capacite -> 403 liste', r.status_code == 403, r.content)
        r = j(GESTION, 'post', admin_sans, corps_base)
        ok('admin sans capacite -> 403 create', r.status_code == 403, r.content)

        r = j(GESTION, 'post', superadmin, corps_base)
        ok('superadmin create -> 201', r.status_code == 201, r.content)
        fid = r.json()['id']
        ok('compteurs a 0 a la creation',
           (r.json()['nb_actives'], r.json()['nb_en_attente'], r.json()['nb_pubs_total']) == (0, 0, 0))

        r = j(GESTION, 'get', superadmin)
        ok('superadmin liste -> 200, formule presente',
           r.status_code == 200 and any(x['id'] == fid for x in resultats(r)), r.content)

        r = j(f'{GESTION}{fid}/', 'get', superadmin)
        ok('superadmin retrieve -> 200', r.status_code == 200 and r.json()['nom'] == 'Formule Test QA')

        r = j(f'{GESTION}{fid}/', 'patch', admin_avec, {'prix': 6000})
        ok('admin avec capacite -> patch 200, prix modifie',
           r.status_code == 200 and r.json()['prix'] == 6000, r.content)

        nb_journal_avant = JournalModeration.objects.filter(action='pub_formule_creer').count()
        r2 = j(GESTION, 'post', superadmin, {**corps_base, 'nom': 'Formule Journal Test'})
        ok('journal : creation tracee',
           JournalModeration.objects.filter(action='pub_formule_creer').count() == nb_journal_avant + 1)
        e = JournalModeration.objects.filter(action='pub_formule_creer').latest('cree_le')
        ok('   acteur = l\'admin, motif nomme la formule',
           e.acteur_id == superadmin.id and 'Formule Journal Test' in e.motif, e.motif)

        nb_modif_avant = JournalModeration.objects.filter(action='pub_formule_modif').count()
        r = j(f'{GESTION}{fid}/', 'patch', superadmin,
              {'prix': 7777, 'quota_partenaires': 9, 'nb_images_max': 3})
        ok('patch multi-champs -> 200', r.status_code == 200, r.content)
        e = JournalModeration.objects.filter(action='pub_formule_modif').latest('cree_le')
        ok('journal modification : prix et quota en ancien -> nouveau',
           JournalModeration.objects.filter(action='pub_formule_modif').count() == nb_modif_avant + 1
           and 'prix 6000 → 7777' in e.motif and 'quota 5 → 9' in e.motif, e.motif)

        r = j(f'{GESTION}{fid}/', 'delete', superadmin)
        ok('delete formule neuve (aucune pub) -> 204', r.status_code == 204, r.content)
        ok('vraiment supprimee', not FormulePublicite.objects.filter(id=fid).exists())

        print('\n=== 2. VALIDATIONS (chacune, 400 par champ) ===')
        _compteur_ko = [0]
        def ko(corps, champ, label):
            _compteur_ko[0] += 1
            # nom unique par appel : isole le champ teste (sauf si "nom"
            # lui-meme est le champ teste par ce cas).
            base = {**corps_base, 'nom': f'{corps_base["nom"]} KO{_compteur_ko[0]}'}
            r = j(GESTION, 'post', superadmin, {**base, **corps})
            present = r.status_code == 400 and champ in (r.json().get('details') or r.json())
            ok(f'{label} -> 400 sur "{champ}"', present, r.content)

        ko({'nom': ''}, 'nom', 'nom vide')
        r = j(GESTION, 'post', superadmin, corps_base)
        ok('formule de reference creee', r.status_code == 201, r.content)
        ko({'nom': corps_base['nom'].upper()}, 'nom', 'nom deja pris (casse differente)')
        ko({'prix': -1}, 'prix', 'prix negatif')
        ko({'duree_jours': 0}, 'duree_jours', 'duree_jours = 0')
        ko({'passages_par_jour': 0}, 'passages_par_jour', 'passages_par_jour = 0')
        ko({'duree_affichage_secondes': 0}, 'duree_affichage_secondes', 'duree_affichage_secondes = 0')
        ko({'quota_partenaires': 0}, 'quota_partenaires', 'quota_partenaires = 0 (illimite refuse)')
        ko({'types_affichage': []}, 'types_affichage', 'types_affichage vide')
        ko({'types_affichage': ['carrousel', 'holodeck']}, 'types_affichage', 'types_affichage inconnu')
        ko({'passages_par_type': {'interstitiel': 3}}, 'passages_par_type',
           'passages_par_type : cle hors types_affichage')
        ko({'passages_par_type': {'carrousel': -1}}, 'passages_par_type',
           'passages_par_type : valeur negative')
        ko({'nb_images_max': 0}, 'nb_images_max', 'nb_images_max = 0')
        ko({'cible_pourcentage_actifs': 0}, 'cible_pourcentage_actifs', 'cible_pourcentage_actifs = 0')
        ko({'cible_pourcentage_actifs': 101}, 'cible_pourcentage_actifs', 'cible_pourcentage_actifs = 101')
        r = j(GESTION, 'post', superadmin, {**corps_base, 'nom': 'F video',
              'video_autorisee': True, 'duree_video_max_secondes': 0})
        ok('duree_video_max_secondes = 0 avec video_autorisee=True -> 400',
           r.status_code == 400 and 'duree_video_max_secondes' in r.json()['details'], r.content)
        r = j(GESTION, 'post', superadmin, {**corps_base, 'nom': 'F cible ok',
              'cible_pourcentage_actifs': None})
        ok('cible_pourcentage_actifs = null -> accepte', r.status_code == 201, r.content)

        print('\n=== 3. SUPPRESSION utilisee vs neuve ===')
        formule_utilisee = FormulePublicite.objects.create(
            nom='Utilisee QA', prix=1000, quota_partenaires=5, types_affichage=['carrousel'])
        Publicite.objects.create(
            partenaire=pa, formule=formule_utilisee, titre='X', portee='departement',
            image_couverture='publicites/couvertures/x.jpg', statut='brouillon')
        r = j(f'{GESTION}{formule_utilisee.id}/', 'delete', superadmin)
        ok('suppression formule utilisee (meme par un seul brouillon) -> 409',
           r.status_code == 409 and 'utilisée par 1 campagne' in r.json()['message'], r.content)
        ok('formule toujours en base', FormulePublicite.objects.filter(id=formule_utilisee.id).exists())
        formule_neuve = FormulePublicite.objects.create(
            nom='Neuve QA', prix=1000, quota_partenaires=5, types_affichage=['carrousel'])
        r = j(f'{GESTION}{formule_neuve.id}/', 'delete', superadmin)
        ok('suppression formule neuve -> 204', r.status_code == 204, r.content)

        print('\n=== 4. DESACTIVATION -> absente du GET partenaire ===')
        formule_dispo = FormulePublicite.objects.create(
            nom='Dispo QA', prix=1000, quota_partenaires=5,
            types_affichage=['carrousel'], est_active=True)
        r = j('/api/v1/publicites/formules/', 'get', pa.user)
        ok('avant desactivation : visible du partenaire',
           any(f['nom'] == 'Dispo QA' for f in resultats(r)), r.content)
        nb_avant = JournalModeration.objects.filter(action='pub_formule_desact').count()
        r = j(f'{GESTION}{formule_dispo.id}/', 'patch', superadmin, {'est_active': False})
        ok('PATCH est_active=false -> 200', r.status_code == 200 and r.json()['est_active'] is False, r.content)
        ok('journal : desactivation tracee',
           JournalModeration.objects.filter(action='pub_formule_desact').count() == nb_avant + 1)
        r = j('/api/v1/publicites/formules/', 'get', pa.user)
        ok('apres desactivation : absente du GET /publicites/formules/ (deja filtre est_active=True)',
           not any(f['nom'] == 'Dispo QA' for f in resultats(r)), r.content)
        nb_avant = JournalModeration.objects.filter(action='pub_formule_react').count()
        r = j(f'{GESTION}{formule_dispo.id}/', 'patch', superadmin, {'est_active': True})
        ok('reactivation -> journal trace',
           r.status_code == 200
           and JournalModeration.objects.filter(action='pub_formule_react').count() == nb_avant + 1)

        print('\n=== 5. QUOTA sous nb_actives (3A) ===')
        formule_q = FormulePublicite.objects.create(
            nom='Quota QA', prix=1000, quota_partenaires=2, types_affichage=['carrousel'])
        Publicite.objects.create(partenaire=pa, formule=formule_q, titre='a1', portee='departement',
                                 image_couverture='x.jpg', statut='active')
        Publicite.objects.create(partenaire=pa, formule=formule_q, titre='a2', portee='departement',
                                 image_couverture='x.jpg', statut='active')
        r = j(f'{GESTION}{formule_q.id}/', 'patch', superadmin, {'quota_partenaires': 1})
        ok('baisser le quota (2 -> 1) sous nb_actives (2) -> 200, autorise',
           r.status_code == 200 and r.json()['quota_partenaires'] == 1, r.content)
        ok('la reponse renvoie nb_actives pour l\'avertissement Angular',
           r.json()['nb_actives'] == 2)
        candidate = Publicite.objects.create(
            partenaire=pa, formule=formule_q, titre='en attente', portee='departement',
            image_couverture='x.jpg', statut='en_attente_validation')
        ok('activation suivante refusee (quota deja depasse)',
           not appliquer_transition(candidate, 'valider')[0])

        print('\n=== 6. PARAMETRES GENERAUX ===')
        r = j(PARAMS, 'get', admin_sans)
        ok('sans capacite -> 403', r.status_code == 403)
        r = j(PARAMS, 'get', admin_avec)
        ok('avec capacite -> 200, champs reels presents', r.status_code == 200
           and {'affluence_debut', 'affluence_fin', 'calcul_affluence_auto',
                'intervalle_min_interstitiel_secondes', 'validation_auto',
                'interstitiel_minute_min', 'interstitiel_minute_max',
                'interstitiel_ratio_session_courte'} <= set(r.json()), r.json())
        nb_avant = JournalModeration.objects.filter(action='pub_parametres_maj').count()
        r = j(PARAMS, 'patch', superadmin, {'validation_auto': True,
              'intervalle_min_interstitiel_secondes': 400})
        ok('PATCH parametres -> 200', r.status_code == 200
           and r.json()['validation_auto'] is True
           and r.json()['intervalle_min_interstitiel_secondes'] == 400, r.content)
        ok('journal : modification des parametres tracee',
           JournalModeration.objects.filter(action='pub_parametres_maj').count() == nb_avant + 1)
        e = JournalModeration.objects.filter(action='pub_parametres_maj').latest('cree_le')
        ok('   motif liste les champs modifies',
           'validation_auto' in e.motif and 'intervalle_min_interstitiel_secondes' in e.motif, e.motif)
        r = j(PARAMS, 'patch', superadmin, {'interstitiel_ratio_session_courte': 150})
        ok('validation : ratio > 100 -> 400', r.status_code == 400, r.content)
        r = j(PARAMS, 'patch', superadmin,
              {'interstitiel_minute_min': 20, 'interstitiel_minute_max': 5})
        ok('validation : minute_max < minute_min -> 400', r.status_code == 400, r.content)
        ok('parametres inchanges apres les 2 rejets',
           ParametresPublicite.obtenir().interstitiel_ratio_session_courte != 150)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert FormulePublicite.objects.count() == avant_f, 'des formules ont persiste !'
assert Publicite.objects.count() == avant_p, 'des publicites ont persiste !'
print(f'Aucune donnee persistee (formules: {avant_f}, publicites: {avant_p}).')
