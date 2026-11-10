"""Tests : disponibilités des véhicules et hébergements (anti double réservation).

Sémantique : une réservation occupe les jours [date_debut, date_fin[ (véhicule :
jour de restitution libre ; hébergement : jour de départ libre). Seules les
demandes CONFIRMÉES occupent ; nouvelle / en cours ne bloquent rien ;
terminée / annulée / refusée libèrent les dates.

Couvre : attente ne bloque pas ; confirmée bloque ; endpoint jours complets et
unités restantes (hébergement 3 unités) ; refus de création chevauchante
(format {erreur, message, details.jours_complets}) ; bornes de dates ;
confirmation concurrente → 409 ; refus automatique des autres demandes +
historique système + notification ; annulation / fin libèrent ; logement non
concerné ; paramètres de l'endpoint.

Autonome : données propres, limitation de débit désactivée, transaction annulée.
Affiche un total OK / KO.

Execution :
    docker exec -i backend-poufiret python manage.py shell < scripts/test_disponibilites.py
"""
import json, uuid
from datetime import timedelta
from unittest import mock

from django.db import transaction
from django.test import Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Article, Categorie, Hebergement, Logement, Vehicule
from apps.reservations.models import DemandeReservation, HistoriqueDemande
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


def ok(libelle, cond, detail=''):
    global NB_OK
    if cond:
        NB_OK += 1
        print('OK  ', libelle)
    else:
        KO.append(libelle)
        print('FAIL', libelle, detail)


def req(method, url, user=None, corps=None):
    kw = {'secure': True, 'HTTP_HOST': HOST}
    if user is not None:
        kw['HTTP_AUTHORIZATION'] = f'Bearer {AccessToken.for_user(user)}'
    fn = getattr(Client(), method)
    if corps is not None:
        return fn(url, json.dumps(corps), content_type='application/json', **kw)
    return fn(url, **kw)


def telephone_libre():
    while True:
        tel = '+2250' + str(uuid.uuid4().int)[:9].rjust(9, '0')
        if not User.objects.filter(telephone=tel).exists():
            return tel


AUJ = timezone.localdate()


def j(n):
    return AUJ + timedelta(days=n)


def s(n):
    return str(j(n))


try:
    with transaction.atomic():
        uid = uuid.uuid4().hex[:6]
        plan = PlanAbonnement.objects.get(libelle='Basique')
        cat = Categorie.objects.create(nom=f'Dispo QA {uid}', slug=f'dispo-qa-{uid}')

        def utilisateur(role):
            return User.objects.create(telephone=telephone_libre(), username=f't_dsp_{uuid.uuid4().hex[:8]}',
                                       role=role, est_verifie=True, first_name='QA')

        def partenaire(nom, type_partenaire):
            return ProfilPartenaire.objects.create(
                user=utilisateur('partenaire'), plan=plan, nom_commerce=f'{nom} {uid}',
                type_partenaire=type_partenaire, statut='actif', est_visible=True)

        def article(p, type_article, prix):
            return Article.objects.create(partenaire=p, categorie=cat, nom=f'{type_article} {uuid.uuid4().hex[:6]}',
                                          slug=uuid.uuid4().hex[:10], type=type_article, prix=prix, est_actif=True)

        garage = partenaire('Garage dispo QA', 'loueur_voiture')
        hotel = partenaire('Hotel dispo QA', 'hotelier')
        agence = partenaire('Agence dispo QA', 'loueur_maison')
        voiture = Vehicule.objects.create(article=article(garage, 'vehicule', 20000), marque='Toyota', modele='Yaris',
                                          mode='location')
        chambre = Hebergement.objects.create(article=article(hotel, 'hebergement', 15000),
                                             type_hebergement='chambre_double', nb_unites=3)
        villa = Logement.objects.create(article=article(agence, 'logement', 100000), type_logement='villa')
        client_a, client_b, client_c = utilisateur('client'), utilisateur('client'), utilisateur('client')
        V, H = voiture.article_id, chambre.article_id

        def creer(user, objet_id, debut, fin, **extra):
            return req('post', '/api/v1/reservations/', user, {
                'objet_id': objet_id, 'nature': 'reservation', 'date_debut': s(debut), 'date_fin': s(fin), **extra})

        def dispo(objet, params=''):
            type_url = 'vehicules' if objet == V else 'hebergements'
            return req('get', f'/api/v1/locations/{type_url}/{objet}/disponibilites/{params}')

        def confirmer(demande_id, loueur):
            return req('post', f'/api/v1/reservations/{demande_id}/transition/', loueur.user, {'action': 'confirmee'})

        def confirmee_orm(objet_id, p, debut, fin, nb=1, statut='confirmee'):
            return DemandeReservation.objects.create(
                numero=f'RES-DSP-{uuid.uuid4().hex[:8]}', client=client_c, partenaire=p, objet_id=objet_id,
                nature='reservation', statut=statut, date_debut=j(debut), date_fin=j(fin), nb_unites=nb)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 1. VEHICULE : ATTENTE NE BLOQUE PAS, CONFIRMEE BLOQUE ===')
        ra = creer(client_a, V, 1, 4)
        rb = creer(client_b, V, 1, 4)
        ok('2 demandes en attente sur les memes dates -> 201 / 201', ra.status_code == 201 and rb.status_code == 201,
           (ra.content[:200], rb.content[:200]))
        d = dispo(V).json()
        ok('endpoint : rien de complet tant que rien n est confirme', d['unites_total'] == 1
           and d['jours_complets'] == [] and d['unites_restantes'] == {}, d)
        with mock.patch('apps.reservations.services.notifier_utilisateur') as notif:
            r = confirmer(ra.json()['id'], garage)
        ok('confirmation A -> 200', r.status_code == 200 and r.json()['statut'] == 'confirmee', r.content[:200])
        b = DemandeReservation.objects.get(pk=rb.json()['id'])
        ok('B refusee automatiquement (Dates deja reservees)', b.statut == 'refusee'
           and b.raison_refus == 'Dates déjà réservées', (b.statut, b.raison_refus))
        h = HistoriqueDemande.objects.filter(demande=b).last()
        ok('historique : acteur systeme, sans utilisateur', h and h.acteur_role == 'systeme' and h.acteur_id is None
           and 'Dates déjà réservées' in h.commentaire, h and (h.acteur_role, h.commentaire))
        ok('client B notifie du refus', any(c.args[0].id == client_b.id and 'refusée' in c.args[2]
                                          for c in notif.call_args_list), notif.call_args_list)
        d = dispo(V).json()
        ok('endpoint : j1..j3 complets, j4 (restitution) libre',
           d['jours_complets'] == [s(1), s(2), s(3)] and d['unites_restantes'] == {}, d)
        r = creer(client_c, V, 3, 6)
        ok('creation chevauchante -> 400 format attendu', r.status_code == 400
           and r.json().get('message') == 'Ces dates ne sont plus disponibles.'
           and r.json()['details'].get('jours_complets') == [s(3)], r.content)
        ok('message historique conserve (periode occupee)', 'déjà réservé' in r.json()['details']['date_debut'][0])
        r = creer(client_c, V, 4, 6)
        ok('prise en charge le jour de restitution -> 201', r.status_code == 201, r.content[:200])
        d_c = r.json()['id']

        print('\n=== 2. CONFIRMATION CONCURRENTE -> 409 ===')
        # Une autre confirmation est passée entre-temps sur [j5,j7[ (simulée en base).
        concurrente = confirmee_orm(V, garage, 5, 7)
        r = confirmer(d_c, garage)
        ok('confirmation qui ne tient plus -> 409 + message clair', r.status_code == 409
           and 'déjà réservé' in r.json()['message'], (r.status_code, r.content[:200]))
        ok('la demande reste en attente', DemandeReservation.objects.get(pk=d_c).statut == 'nouvelle')
        super_admin = User.objects.create(telephone=telephone_libre(), username=f't_dsp_su_{uid}', role='admin',
                                          is_staff=True, is_superuser=True, est_verifie=True)
        r = req('post', f'/api/v1/reservations/admin/demandes/{d_c}/transition/', super_admin, {'action': 'confirmee'})
        ok('meme regle cote admin -> 409', r.status_code == 409, (r.status_code, r.content[:200]))

        print('\n=== 3. ANNULATION / FIN LIBERENT ===')
        r = req('post', f"/api/v1/reservations/{ra.json()['id']}/annuler/", client_a, {'commentaire': 'Changement'})
        ok('annulation de la confirmee -> 200', r.status_code == 200, r.content[:200])
        d = dispo(V).json()
        ok('endpoint : j1..j3 liberes (cache invalide)', s(1) not in d['jours_complets'] and s(3) not in d['jours_complets'],
           d['jours_complets'])
        ok('creation sur les dates liberees -> 201', creer(client_b, V, 1, 3).status_code == 201)
        concurrente.statut = 'terminee'
        concurrente.save()
        ok('terminee ne bloque plus', s(5) not in dispo(V).json()['jours_complets'])
        refusee = confirmee_orm(V, garage, 20, 22, statut='refusee')
        ok('refusee ne bloque pas', s(20) not in dispo(V).json()['jours_complets'] and refusee.pk)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 4. HEBERGEMENT 3 UNITES ===')
        confirmee_orm(H, hotel, 1, 3, nb=2)   # nuits j1, j2
        confirmee_orm(H, hotel, 2, 4, nb=1)   # nuits j2, j3 (départ j4)
        d = dispo(H).json()
        ok('unites_total 3, j2 complet, j1 -> 1 restante, j3 -> 2 restantes, j4 libre',
           d['unites_total'] == 3 and d['jours_complets'] == [s(2)]
           and d['unites_restantes'] == {s(1): 1, s(3): 2}, d)
        r = creer(client_a, H, 2, 3)
        ok('nuit complete -> 400 jours_complets', r.status_code == 400
           and r.json()['details'].get('jours_complets') == [s(2)], r.content)
        r = creer(client_a, H, 1, 2, nb_unites=2)
        ok('2 unites sur j1 (1 restante) -> 400', r.status_code == 400
           and r.json()['details'].get('jours_complets') == [s(1)], r.content)
        ok('4 unites (> capacite totale) -> 400 sans jours_complets', set(
            creer(client_a, H, 6, 7, nb_unites=4).json()['details']) == {'nb_unites'})
        r1 = creer(client_a, H, 3, 5, nb_unites=2, nb_adultes=2)
        ok('2 unites sur [j3,j5[ (2 restantes j3) -> 201', r1.status_code == 201, r1.content[:200])
        r2 = creer(client_b, H, 4, 6, nb_unites=3, nb_adultes=3)
        ok('3 unites a partir du jour de depart (j4) -> 201', r2.status_code == 201, r2.content[:200])
        r3 = creer(client_c, H, 3, 4, nb_unites=1)
        ok('1 unite sur j3 -> 201', r3.status_code == 201)
        with mock.patch('apps.reservations.services.notifier_utilisateur'):
            r = confirmer(r1.json()['id'], hotel)
        ok('confirmation 2 unites sur [j3,j5[ -> 200', r.status_code == 200, r.content[:200])
        st = {k: DemandeReservation.objects.get(pk=v.json()['id']).statut for k, v in (('r2', r2), ('r3', r3))}
        ok('refus auto : r2 (j4 n a plus 3 unites) refusee, r3 (j3 complet) refusee',
           st == {'r2': 'refusee', 'r3': 'refusee'}, st)
        d = dispo(H).json()
        ok('endpoint apres confirmation : j2 et j3 complets, j4 -> 1 restante',
           d['jours_complets'] == [s(2), s(3)] and d['unites_restantes'] == {s(1): 1, s(4): 1}, d)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 5. LOGEMENT NON CONCERNE ===')
        l1 = req('post', '/api/v1/reservations/', client_a, {'objet_id': villa.article_id, 'nature': 'reservation',
                                                              'date_debut': s(1), 'date_fin': s(30)})
        l2 = req('post', '/api/v1/reservations/', client_b, {'objet_id': villa.article_id, 'nature': 'reservation',
                                                              'date_debut': s(1), 'date_fin': s(30)})
        ok('2 demandes logement memes dates -> 201', l1.status_code == 201 and l2.status_code == 201)
        with mock.patch('apps.reservations.services.notifier_utilisateur'):
            r = confirmer(l1.json()['id'], agence)
        ok('confirmation logement -> 200, autre demande NON refusee (regle M1 inchangee)', r.status_code == 200
           and DemandeReservation.objects.get(pk=l2.json()['id']).statut == 'nouvelle')
        ok('pas d endpoint de disponibilites pour un logement -> 404',
           req('get', f'/api/v1/locations/vehicules/{villa.article_id}/disponibilites/').status_code == 404)

        # ═══════════════════════════════════════════════════════════════
        print('\n=== 6. PARAMETRES DE L ENDPOINT ===')
        d = dispo(V).json()
        ok('defaut : aujourd hui -> +180 jours', d['du'] == str(AUJ) and d['au'] == s(180), (d['du'], d['au']))
        d = dispo(V, f'?du={s(1)}&au={s(3)}').json()
        ok('?du=&au= bornes incluses', d['du'] == s(1) and d['au'] == s(3))
        ok('date invalide -> 400', dispo(V, '?du=demain').status_code == 400)
        ok('au < du -> 400', dispo(V, f'?du={s(5)}&au={s(1)}').status_code == 400)
        ok('plus de 366 jours -> 400', dispo(V, f'?du={s(0)}&au={s(366)}').status_code == 400)
        ok('366 jours -> 200', dispo(V, f'?du={s(0)}&au={s(365)}').status_code == 200)
        ok('objet introuvable -> 404',
           req('get', '/api/v1/locations/hebergements/999999999/disponibilites/').status_code == 404)
        voiture.disponibilite = 'indisponible'
        voiture.save()
        d = dispo(V, f'?du={s(1)}&au={s(2)}').json()
        ok('vehicule indisponible : tous les jours complets (cache invalide par la fiche)',
           d['jours_complets'] == [s(1), s(2)], d)

        raise Rollback()
except Rollback:
    print('\nRollback effectue (rien persiste).')

print(f'\n=== TOTAL : {NB_OK} OK / {len(KO)} KO ===')
if KO:
    print('KO :', *KO, sep='\n - ')
    raise SystemExit(1)
