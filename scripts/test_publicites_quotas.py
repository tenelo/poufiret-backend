"""Tests : quota par formule, endpoint quotas admin, annulation de soumission,
brouillons invisibles pour l'admin, filtres admin des pubs.

Execution (tout est annule a la fin) :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_publicites_quotas.py
"""
import json

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from rest_framework_simplejwt.tokens import AccessToken

from apps.administration.models import JournalModeration, PermissionsAdmin
from apps.payments.models import Paiement
from apps.publicites.models import FormulePublicite, Publicite
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


avant = Publicite.objects.count()
try:
    with transaction.atomic():
        c = Client()
        S = Publicite.Statut
        superadmin = User.objects.filter(is_superuser=True).first()
        pa = ProfilPartenaire.objects.get(id=2)    # Salon Awa (forfait departement)
        pb = ProfilPartenaire.objects.get(id=1)    # Business Center (forfait region)
        ua, ub = pa.user, pb.user
        decouverte = FormulePublicite.objects.get(nom='Découverte')
        exclusif = FormulePublicite.objects.get(nom='Exclusif')

        def pub(formule, statut, partenaire=pa, titre='T', portee='departement', **kw):
            return Publicite.objects.create(
                partenaire=partenaire, formule=formule, titre=titre, portee=portee,
                image_couverture='publicites/couvertures/x.jpg', statut=statut, **kw)

        print('\n=== 1. QUOTA : activation par formule ===')
        Publicite.objects.filter(statut='active').update(statut='terminee')   # terrain propre (annule)
        pub(decouverte, S.ACTIVE, titre='deja active 1')
        cible = pub(decouverte, S.EN_ATTENTE_VALIDATION, titre='a activer')
        ok('Decouverte : 1 active, quota 20 -> quota disponible', True)
        r = c.post(f'/api/v1/publicites/{cible.id}/transition/valider/', secure=True, **h(superadmin))
        ok('Decouverte avec 1 active -> valider = 200 (activee)',
           r.status_code == 200 and r.json()['statut'] == 'active', r.content)

        pub(exclusif, S.ACTIVE, titre='exclusif actif')
        cible = pub(exclusif, S.EN_ATTENTE_VALIDATION, titre='exclusif 2')
        r = c.post(f'/api/v1/publicites/{cible.id}/transition/valider/', secure=True, **h(superadmin))
        ok('Exclusif (quota 1) avec 1 active -> refus 409', r.status_code == 409, r.content)
        print('     message :', r.json()['message'])
        ok('   le message nomme la formule et le compte (1/1)',
           'Exclusif' in r.json()['message'] and '1/1' in r.json()['message'])
        ok('   la pub reste en attente de validation',
           Publicite.objects.get(id=cible.id).statut == S.EN_ATTENTE_VALIDATION)

        # derniere place : quota 3, 2 actives -> la 3e passe, la 4e est refusee
        FormulePublicite.objects.filter(id=decouverte.id).update(quota_partenaires=3)
        decouverte.refresh_from_db()
        Publicite.objects.filter(formule=decouverte, statut='active').update(statut='terminee')
        pub(decouverte, S.ACTIVE, titre='a1'); pub(decouverte, S.ACTIVE, titre='a2')
        p3 = pub(decouverte, S.EN_ATTENTE_VALIDATION, titre='derniere place')
        p4 = pub(decouverte, S.EN_ATTENTE_VALIDATION, titre='de trop')
        ok('activation qui remplit EXACTEMENT la derniere place (2/3 -> 3/3) = OK',
           appliquer_transition(p3, 'valider')[0])
        ok('la suivante (3/3 plein) = refusee', not appliquer_transition(p4, 'valider')[0])
        # une pub deja active ne se bloque pas elle-meme (exclusion de la pub en cours)
        ok('la pub en cours d\'activation n\'est pas comptee (quota 1, elle seule) ',
           (lambda f: (Publicite.objects.filter(formule=f).update(statut='terminee'),
                       appliquer_transition(pub(f, S.EN_ATTENTE_VALIDATION), 'valider')[0])[1])(
               exclusif))

        print('\n=== 2. ENDPOINT QUOTAS PAR FORMULE ===')
        Publicite.objects.filter(formule=decouverte).update(statut='terminee')   # repart d'une formule propre
        pub(decouverte, S.ACTIVE); pub(decouverte, S.ACTIVE)
        pub(decouverte, S.EN_ATTENTE_PAIEMENT); pub(decouverte, S.EN_ATTENTE_VALIDATION)
        pub(decouverte, S.BROUILLON)                       # ne compte nulle part
        c.get('/api/v1/publicites/admin/formules/', secure=True, **h(superadmin))
        with CaptureQueriesContext(connection) as ctx:
            r = c.get('/api/v1/publicites/admin/formules/', secure=True, **h(superadmin))
        ok('GET admin/formules/ -> 200', r.status_code == 200, r.content)
        lignes = {f['nom']: f for f in r.json()['formules']}
        ok('une ligne par formule (%d)' % len(lignes), len(lignes) == FormulePublicite.objects.count())
        d = lignes['Découverte']
        ok('Decouverte : 2 actives, quota 3, 1 place, 2 en attente (1 paiement + 1 validation), brouillon ignore',
           (d['nb_actives'], d['quota_partenaires'], d['places_restantes'], d['nb_en_attente'],
            d['nb_en_attente_paiement'], d['nb_en_attente_validation']) == (2, 3, 1, 2, 1, 1), d)
        ok('champs exacts id/nom/prix/quota/nb_actives/places_restantes/nb_en_attente presents',
           {'id', 'nom', 'prix', 'quota_partenaires', 'nb_actives', 'places_restantes',
            'nb_en_attente'} <= set(d))
        for f in FormulePublicite.objects.all():
            manuel = Publicite.objects.filter(formule=f, statut='active').count()
            ok(f'   {f.nom} : nb_actives = {manuel}', lignes[f.nom]['nb_actives'] == manuel)
        ok('UNE requete agregee : %d requetes SQL au total (dont 1 lecture JWT), sans N+1' % len(ctx),
           len(ctx) <= 2, [q['sql'][:80] for q in ctx.captured_queries])
        r = c.get('/api/v1/publicites/admin/formules/', secure=True, **h(ua))
        ok('partenaire -> 403', r.status_code == 403)

        print('\n=== 3. ANNULER LA SOUMISSION ===')
        url = lambda p: f'/api/v1/publicites/mes-publicites/{p.id}/annuler-soumission/'
        soumise = pub(decouverte, S.EN_ATTENTE_PAIEMENT, titre='soumise a annuler')
        nb_journal = JournalModeration.objects.filter(action='pub_annuler').count()
        r = c.post(url(soumise), secure=True, **h(ua))
        ok('proprietaire, en attente de paiement -> 200, statut brouillon',
           r.status_code == 200 and r.json()['statut'] == 'brouillon'
           and Publicite.objects.get(id=soumise.id).statut == S.BROUILLON, r.content)
        e = JournalModeration.objects.filter(action='pub_annuler').first()
        ok('transition journalisee (JournalModeration pub_annuler, acteur = partenaire)',
           JournalModeration.objects.filter(action='pub_annuler').count() == nb_journal + 1
           and e.acteur_id == ua.id and str(soumise.id) in e.motif, e and e.motif)
        for statut, mot in ((S.BROUILLON, "pas été soumise"), (S.EN_ATTENTE_VALIDATION, 'paiement'),
                            (S.ACTIVE, 'déjà active'), (S.TERMINEE, 'terminée'), (S.REJETEE, 'rejetée')):
            p = pub(decouverte, statut)
            r = c.post(url(p), secure=True, **h(ua))
            ok(f'statut {statut} -> 400 « …{mot}… »',
               r.status_code == 400 and mot in r.json()['message'], r.content)
            ok(f'   statut inchange ({statut})', Publicite.objects.get(id=p.id).statut == statut)
        p = pub(decouverte, S.EN_ATTENTE_PAIEMENT)
        p.paiement = Paiement.objects.create(user=ua, partenaire=pa, type_objet='publicite',
                                             montant=1000, statut='confirme')
        p.save()
        r = c.post(url(p), secure=True, **h(ua))
        ok('en attente de paiement MAIS paiement confirme -> 400',
           r.status_code == 400 and 'paiement est déjà confirmé' in r.json()['message'].replace('Un ', 'Le ') or
           r.status_code == 400 and 'confirmé' in r.json()['message'], r.content)
        autre = pub(decouverte, S.EN_ATTENTE_PAIEMENT, partenaire=pb)
        r = c.post(url(autre), secure=True, **h(ua))
        ok('pub d\'un autre partenaire -> 404, inchangee',
           r.status_code == 404 and Publicite.objects.get(id=autre.id).statut == S.EN_ATTENTE_PAIEMENT, r.content)
        r = c.post(url(autre), secure=True, **h(superadmin))
        ok('compte non partenaire -> 403', r.status_code == 403, r.content)
        r = c.post(url(autre), secure=True, HTTP_HOST=HOST)
        ok('anonyme -> 401', r.status_code == 401)
        # la route generique ne contourne pas les regles
        r = c.post(f'/api/v1/publicites/{p.id}/transition/annuler_soumission/', secure=True, **h(ua))
        ok('route generique transition/annuler_soumission : meme refus (400)', r.status_code == 400, r.content)

        print('\n=== 4. BROUILLONS INVISIBLES POUR L\'ADMIN ===')
        brouillon = pub(decouverte, S.BROUILLON, titre='BROUILLON-SECRET-XYZ')
        attente = pub(decouverte, S.EN_ATTENTE_VALIDATION, titre='ATTENTE-VISIBLE-XYZ')
        r = c.get('/api/v1/publicites/admin/stats/', secure=True, **h(superadmin))
        ids = {x['id'] for x in r.json()['publicites']}
        ok('liste admin : aucun brouillon', str(brouillon.id) not in ids
           and all(x['statut'] != 'brouillon' for x in r.json()['publicites']))
        ok('liste admin : la pub soumise est visible', str(attente.id) in ids)
        ok('compteurs_statut : pas de cle brouillon', 'brouillon' not in r.json()['compteurs_statut'])
        ok('totaux.nb_publicites = nb de pubs non brouillon',
           r.json()['totaux']['nb_publicites'] == Publicite.objects.exclude(statut='brouillon').count())
        cv = c.get('/api/v1/publicites/admin/export/?type=publicites', secure=True, **h(superadmin)).content.decode()
        ok('export CSV publicites : brouillon absent, pub soumise presente',
           'BROUILLON-SECRET-XYZ' not in cv and 'ATTENTE-VISIBLE-XYZ' in cv)
        r = c.get('/api/v1/publicites/mes-publicites/', secure=True, **h(ua))
        titres = [x.get('titre') for x in (r.json().get('results') if isinstance(r.json(), dict) else r.json())]
        ok('le partenaire voit toujours SES brouillons', 'BROUILLON-SECRET-XYZ' in titres, titres[:5])

        print('\n=== 5. FILTRES ADMIN ===')
        Publicite.objects.exclude(id__in=[]).filter(titre__startswith='__').delete()
        def liste(q=''):
            r = c.get('/api/v1/publicites/admin/stats/' + q, secure=True, **h(superadmin))
            return r, (r.json()['publicites'] if r.status_code == 200 else [])
        base_ids = {p['id'] for p in liste()[1]}
        r, l = liste('?statut=active')
        ok('?statut=active (un seul)', r.status_code == 200 and l and all(x['statut'] == 'active' for x in l))
        r, l = liste('?statut=active,en_attente_validation')
        ok('?statut=a,b (virgules)', {x['statut'] for x in l} == {'active', 'en_attente_validation'})
        r, l = liste('?statut=active&statut=terminee')
        ok('?statut=a&statut=b (repete)', {x['statut'] for x in l} == {'active', 'terminee'})
        r, _ = liste('?statut=nimportequoi')
        ok('statut inconnu -> 400 message francais', r.status_code == 400 and 'Statut inconnu' in r.json()['message'], r.content)
        ok('?statut=brouillon -> liste vide (jamais visible)', liste('?statut=brouillon')[1] == [])
        r, l = liste(f'?formule={exclusif.id}')
        ok('?formule=<uuid>', l and all(x['formule_id'] == str(exclusif.id) for x in l))
        ok('?formule invalide -> 400', liste('?formule=abc')[0].status_code == 400)
        r, l = liste(f'?partenaire={pb.id}')
        ok('?partenaire=<id>', l and all(x['partenaire_id'] == pb.id for x in l))
        pub(decouverte, S.ACTIVE, partenaire=pa, titre='Recherche-ZEBULON-unique')
        ok('?search= sur le titre', [x['titre'] for x in liste('?search=zebulon')[1]] == ['Recherche-ZEBULON-unique'])
        ok('?search= sur le nom du partenaire',
           liste('?search=' + pa.nom_commerce[:5])[1] and all(x['nom_partenaire'] == pa.nom_commerce
                                                             for x in liste('?search=' + pa.nom_commerce)[1]))
        # portee EFFECTIVE : pub stockee 'departement' d'un partenaire au forfait region => region
        pub(decouverte, S.ACTIVE, partenaire=pb, titre='Effective-Region', portee='departement')
        pub(decouverte, S.ACTIVE, partenaire=pa, titre='Effective-Departement', portee='departement')
        pub(decouverte, S.ACTIVE, partenaire=pa, titre='Effective-District', portee='district')
        t = lambda q: {x['titre'] for x in liste(q)[1]}
        ok('?portee=region : inclut la pub (forfait region, stockee departement)',
           'Effective-Region' in t('?portee=region') and 'Effective-Departement' not in t('?portee=region'))
        ok('?portee=departement : forfait departement seulement',
           'Effective-Departement' in t('?portee=departement') and 'Effective-Region' not in t('?portee=departement')
           and 'Effective-District' not in t('?portee=departement'))
        ok('?portee=district', 'Effective-District' in t('?portee=district'))
        ok('?portee invalide -> 400', liste('?portee=monde')[0].status_code == 400)
        rr, ll = liste('?portee=region')
        ok('portee / portee_effective exposes dans chaque ligne', all('portee_effective' in x and 'portee' in x for x in ll))
        # compteurs : ignorent ?statut mais respectent les autres filtres
        r, _ = liste(f'?formule={decouverte.id}&statut=active')
        cpt = r.json()['compteurs_statut']
        attendu = {s: Publicite.objects.filter(formule=decouverte, statut=s).count()
                   for s in ('en_attente_paiement', 'en_attente_validation', 'active', 'terminee', 'rejetee')}
        ok('compteurs_statut (hors statut, filtres formule respectes) = comptage reel',
           all(cpt[s] == n for s, n in attendu.items()) and cpt['total'] == sum(attendu.values()), (cpt, attendu))
        anciens = {'id', 'titre', 'formule', 'statut', 'nb_personnes_touchees', 'nb_impressions', 'nb_clics',
                   'taux_clic', 'impressions_par_type', 'cible_pourcentage', 'cible_atteinte',
                   'debut_diffusion', 'fin_diffusion', 'partenaire_id', 'nom_partenaire',
                   'partenaire_telephone', 'formule_id', 'prix_formule', 'image_couverture', 'video'}
        rr, ll = liste()
        ok('aucun champ existant retire (ligne)', anciens <= set(ll[0]), anciens - set(ll[0]))
        ok('aucun champ existant retire (totaux)',
           {'nb_publicites', 'nb_actives', 'total_impressions', 'total_personnes_touchees',
            'total_clics'} <= set(rr.json()['totaux']))
        r = c.get('/api/v1/publicites/admin/stats/', secure=True, **h(ua))
        ok('partenaire sur la liste admin -> 403 (permission inchangee)', r.status_code == 403)

        print(f'\n=== {NB} verifications reussies ===')
        raise Rollback('annulation volontaire')
except Rollback as e:
    print('Rollback effectue :', e)

assert Publicite.objects.count() == avant, 'des donnees ont persiste'
print('Aucune donnee persistee (publicites : %d avant/apres).' % avant)
