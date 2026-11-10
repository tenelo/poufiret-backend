"""Statistiques d'usage (admin, lecture seule) calculées à partir des données
déjà collectées : RechercheLog, EvenementApp, Commande (+ HistoriqueCommande
pour les motifs d'annulation), VueVitrine, VueArticle.

GET /api/v1/administration/statistiques-usage/<recherches|entonnoir|
contacts-partenaires|activite|resume>/ — permission voir_stats (super-admin
toujours autorisé).

Paramètres communs :
- ?du=YYYY-MM-DD&au=YYYY-MM-DD : bornes incluses, jours en heure locale
  (Africa/Abidjan) ; défaut : les 30 derniers jours (aujourd'hui inclus) ;
  366 jours au plus.
- ?departement=<id> : département du PARTENAIRE pour les événements,
  commandes et vues ; de l'UTILISATEUR pour les recherches (les recherches
  anonymisées — sans consentement — sont alors exclues).

Tout est agrégé en base (COUNT / SUM / GROUP BY) ; Python ne parcourt que
les lignes agrégées (au plus une par jour, heure, terme, catégorie…).
Les taux sont des ratios (0 à 1, 4 décimales) ; null si le dénominateur est 0.
"""
from datetime import date, datetime, time, timedelta

from decimal import Decimal

from django.db.models import (
    CharField, Count, DecimalField, F, FloatField, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value,
)
from django.db.models.functions import (
    Cast, Coalesce, Concat, ExtractHour, ExtractIsoWeekDay, Lower, NullIf, Trim, TruncDate,
)
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import EvenementApp, RechercheLog, VueVitrine
from apps.catalog.models import Categorie, VueArticle
from apps.core.exceptions import ErreurMetier
from apps.core.permissions import ADroitDe
from apps.orders.models import Commande, HistoriqueCommande
from apps.users.models import ProfilPartenaire

PERMISSION = [IsAuthenticated, ADroitDe('voir_stats')]
JOURS_DEFAUT = 30
JOURS_MAX = 366
TOP = 50
CONTACTS = ('appel_partenaire', 'whatsapp_partenaire', 'itineraire_partenaire')
JOURS_SEMAINE = {1: 'Lundi', 2: 'Mardi', 3: 'Mercredi', 4: 'Jeudi', 5: 'Vendredi', 6: 'Samedi', 7: 'Dimanche'}


# ═══════════════════════════════════════════════════════════════════════
# Période et filtres
# ═══════════════════════════════════════════════════════════════════════

class Periode:
    def __init__(self, du, au, departement=None):
        self.du, self.au, self.departement = du, au, departement
        tz = timezone.get_current_timezone()
        self.debut = timezone.make_aware(datetime.combine(du, time.min), tz)
        self.fin = timezone.make_aware(datetime.combine(au + timedelta(days=1), time.min), tz)  # exclue

    @property
    def nb_jours(self):
        return (self.au - self.du).days + 1

    def precedente(self):
        """Période de même longueur, juste avant."""
        au = self.du - timedelta(days=1)
        return Periode(au - timedelta(days=self.nb_jours - 1), au, self.departement)

    def jours(self):
        return [self.du + timedelta(days=i) for i in range(self.nb_jours)]

    def en_dict(self):
        return {'du': self.du.isoformat(), 'au': self.au.isoformat(), 'nb_jours': self.nb_jours,
                'departement': self.departement}

    # Querysets de la période (et du département) ─────────────────────
    def _dep(self, qs, champ):
        return qs.filter(**{champ: self.departement}) if self.departement else qs

    def recherches(self):
        return self._dep(RechercheLog.objects.filter(cree_le__gte=self.debut, cree_le__lt=self.fin),
                         'utilisateur__departement_id')

    def evenements(self):
        return self._dep(EvenementApp.objects.filter(cree_le__gte=self.debut, cree_le__lt=self.fin),
                         'partenaire__departement_id')

    def commandes(self):
        return self._dep(Commande.objects.filter(created_at__gte=self.debut, created_at__lt=self.fin),
                         'partenaire__departement_id')

    def vues_vitrine(self):
        return self._dep(VueVitrine.objects.filter(cree_le__gte=self.debut, cree_le__lt=self.fin),
                         'partenaire__departement_id')

    def vues_article(self):
        return self._dep(VueArticle.objects.filter(date_vue__gte=self.debut, date_vue__lt=self.fin),
                         'article__partenaire__departement_id')


def lire_periode(request):
    p = request.query_params
    aujourd_hui = timezone.localdate()

    def _date(cle, defaut):
        brut = p.get(cle)
        if not brut:
            return defaut
        try:
            return date.fromisoformat(brut)
        except ValueError:
            raise ErreurMetier(f'{cle} : date attendue au format AAAA-MM-JJ.', {cle: brut})

    au = _date('au', aujourd_hui)
    du = _date('du', au - timedelta(days=JOURS_DEFAUT - 1))
    if du > au:
        raise ErreurMetier('du doit être antérieur ou égal à au.', {'du': du.isoformat(), 'au': au.isoformat()})
    if (au - du).days + 1 > JOURS_MAX:
        raise ErreurMetier(f'Période limitée à {JOURS_MAX} jours.', {'nb_jours': (au - du).days + 1})
    departement = p.get('departement') or None
    if departement is not None:
        if not departement.isdigit():
            raise ErreurMetier('departement : identifiant numérique attendu.', {'departement': departement})
        departement = int(departement)
    return Periode(du, au, departement)


def taux(numerateur, denominateur):
    return round(numerateur / denominateur, 4) if denominateur else None


def _texte(champ):
    return Coalesce(Cast(champ, CharField()), Value(''))


def paniers_distincts(evenements):
    """Paniers avec au moins un ajout : couples distincts utilisateur ×
    partenaire × catégorie × jour (un ajout anonymisé compte pour un panier)."""
    cle = Concat(Coalesce(Cast('utilisateur_id', CharField()), Concat(Value('e'), Cast('id', CharField()))),
                 Value('|'), _texte('partenaire_id'), Value('|'), _texte('categorie_id'),
                 Value('|'), Cast(TruncDate('cree_le'), CharField()), output_field=CharField())
    return evenements.filter(type='panier_ajout').aggregate(n=Count(cle, distinct=True))['n']


class _Vue(APIView):
    permission_classes = PERMISSION

    def get(self, request):
        periode = lire_periode(request)
        return Response({'periode': periode.en_dict(), **self.calculer(periode, request)})


# ═══════════════════════════════════════════════════════════════════════
# 1. Recherches
# ═══════════════════════════════════════════════════════════════════════

class RecherchesUsageView(_Vue):
    """Top 50 des termes (terme_normalise) et top 50 des termes sans résultat."""

    def calculer(self, periode, request):
        qs = periode.recherches()
        totaux = qs.aggregate(nb=Count('id'), nb_avec_clic=Count('id', filter=Q(clique_le__isnull=False)),
                              nb_sans_resultat=Count('id', filter=Q(nb_resultats=0)),
                              nb_termes=Count('terme_normalise', distinct=True))
        termes = (qs.values('terme_normalise')
                  .annotate(nb=Count('id'), nb_avec_clic=Count('id', filter=Q(clique_le__isnull=False)),
                            nb_sans_resultat=Count('id', filter=Q(nb_resultats=0)))
                  .order_by('-nb', 'terme_normalise')[:TOP])
        sans = (qs.filter(nb_resultats=0).values('terme_normalise')
                .annotate(nb=Count('id'), derniere=Max('cree_le'))
                .order_by('-nb', 'terme_normalise')[:TOP])
        return {
            'totaux': {**totaux, 'taux_clic': taux(totaux['nb_avec_clic'], totaux['nb']),
                       'taux_sans_resultat': taux(totaux['nb_sans_resultat'], totaux['nb'])},
            'top_termes': [{**t, 'taux_clic': taux(t['nb_avec_clic'], t['nb'])} for t in termes],
            'top_sans_resultat': [{'terme_normalise': t['terme_normalise'], 'nb': t['nb'],
                                   'derniere_recherche': t['derniere']} for t in sans],
        }


# ═══════════════════════════════════════════════════════════════════════
# 2. Entonnoir panier → commande → livraison
# ═══════════════════════════════════════════════════════════════════════

def _motif():
    return Lower(Trim('commentaire'))


class EntonnoirUsageView(_Vue):
    """Paniers avec ajout → commandes créées → livrées / annulées (commandes
    créées dans la période, statut actuel), motifs d'annulation, par catégorie."""

    def calculer(self, periode, request):
        evts = periode.evenements()
        cmd = periode.commandes()
        global_ = cmd.aggregate(
            nb_commandes=Count('id'), nb_livrees=Count('id', filter=Q(statut='livree')),
            nb_annulees=Count('id', filter=Q(statut='annulee')), nb_refusees=Count('id', filter=Q(statut='refusee')),
            nb_expirees=Count('id', filter=Q(statut='expiree')),
            montant_livre=Coalesce(Sum('total', filter=Q(statut='livree')), Value(Decimal(0)), output_field=DecimalField()))
        global_['montant_livre'] = int(global_['montant_livre'])
        nb_ajouts = evts.filter(type='panier_ajout').count()
        nb_paniers = paniers_distincts(evts)

        # Motifs : historique de l'annulation des commandes annulées de la période.
        hist = HistoriqueCommande.objects.filter(statut='annulee', commande__in=cmd.filter(statut='annulee'))
        par_acteur = list(hist.values('acteur_role').annotate(nb=Count('commande', distinct=True))
                          .order_by('-nb', 'acteur_role'))
        motifs = list(hist.annotate(motif=_motif()).values('motif')
                      .annotate(nb=Count('commande', distinct=True)).order_by('-nb', 'motif')[:20])
        motifs_refus = list(cmd.filter(statut='refusee').annotate(motif=Lower(Trim('raison_refus')))
                            .values('motif').annotate(nb=Count('id')).order_by('-nb', 'motif')[:20])

        # Par catégorie : paniers (événements) et commandes, regroupés par catégorie.
        cle_panier = Concat(Coalesce(Cast('utilisateur_id', CharField()), Concat(Value('e'), Cast('id', CharField()))),
                            Value('|'), _texte('partenaire_id'), Value('|'), Cast(TruncDate('cree_le'), CharField()),
                            output_field=CharField())
        paniers_cat = {l['categorie_id']: l for l in evts.filter(type='panier_ajout').values('categorie_id')
                       .annotate(nb_ajouts=Count('id'), nb_paniers=Count(cle_panier, distinct=True)).order_by()}
        cmd_cat = {l['categorie_id']: l for l in cmd.values('categorie_id').annotate(
            nb_commandes=Count('id'), nb_livrees=Count('id', filter=Q(statut='livree')),
            nb_annulees=Count('id', filter=Q(statut='annulee'))).order_by()}
        ids = set(paniers_cat) | set(cmd_cat)
        noms = dict(Categorie.objects.filter(id__in=[i for i in ids if i]).values_list('id', 'nom'))
        par_categorie = []
        for cid in ids:
            pc, cc = paniers_cat.get(cid, {}), cmd_cat.get(cid, {})
            ligne = {'categorie_id': cid, 'categorie_nom': noms.get(cid, 'Sans catégorie'),
                     'nb_ajouts_panier': pc.get('nb_ajouts', 0), 'nb_paniers': pc.get('nb_paniers', 0),
                     'nb_commandes': cc.get('nb_commandes', 0), 'nb_livrees': cc.get('nb_livrees', 0),
                     'nb_annulees': cc.get('nb_annulees', 0)}
            ligne['taux_conversion'] = taux(ligne['nb_commandes'], ligne['nb_paniers'])
            ligne['taux_livraison'] = taux(ligne['nb_livrees'], ligne['nb_commandes'])
            par_categorie.append(ligne)
        par_categorie.sort(key=lambda l: (-l['nb_commandes'], -l['nb_paniers'], l['categorie_nom']))

        return {
            'nb_ajouts_panier': nb_ajouts,
            'nb_paniers_avec_ajout': nb_paniers,
            **global_,
            'taux_conversion': taux(global_['nb_commandes'], nb_paniers),
            'taux_livraison': taux(global_['nb_livrees'], global_['nb_commandes']),
            'taux_annulation': taux(global_['nb_annulees'], global_['nb_commandes']),
            'annulations': {
                'par_acteur': par_acteur,
                'motifs': [{'motif': m['motif'] or '(sans motif)', 'nb': m['nb']} for m in motifs],
            },
            'refus': {'motifs': [{'motif': m['motif'] or '(sans motif)', 'nb': m['nb']} for m in motifs_refus]},
            'par_categorie': par_categorie,
        }


# ═══════════════════════════════════════════════════════════════════════
# 3. Contacts partenaires
# ═══════════════════════════════════════════════════════════════════════

TRIS = ('vues_vitrine', 'appels', 'whatsapp', 'itineraires', 'contacts', 'commandes',
        'taux_contact_commande', 'taux_vue_contact', 'nom_commerce')


def _compte(qs, champ='partenaire'):
    """Sous-requête COUNT par partenaire (pas de jointures multipliées)."""
    sq = (qs.filter(**{champ: OuterRef('pk')}).order_by().values(champ)
          .annotate(n=Count('id')).values('n'))
    return Coalesce(Subquery(sq, output_field=IntegerField()), 0)


class ContactsPartenairesUsageView(_Vue):
    """Par partenaire actif sur la période : vues vitrine, appels, WhatsApp,
    itinéraires, commandes, taux contact → commande.
    ?tri=<champ> ou -<champ> (défaut -contacts) ; ?page=, ?page_size= (20, max 100)."""

    def calculer(self, periode, request):
        p = request.query_params
        tri = p.get('tri', '-contacts')
        if tri.lstrip('-') not in TRIS:
            raise ErreurMetier(f'tri : valeur attendue parmi {", ".join(TRIS)} (préfixe - : décroissant).',
                               {'tri': tri})
        try:
            page = max(1, int(p.get('page', 1)))
            taille = min(100, max(1, int(p.get('page_size', 20))))
        except ValueError:
            raise ErreurMetier('page / page_size : entiers attendus.')
        evts = EvenementApp.objects.filter(cree_le__gte=periode.debut, cree_le__lt=periode.fin)
        vues = VueVitrine.objects.filter(cree_le__gte=periode.debut, cree_le__lt=periode.fin)
        cmd = Commande.objects.filter(created_at__gte=periode.debut, created_at__lt=periode.fin)
        qs = ProfilPartenaire.objects.all()
        if periode.departement:
            qs = qs.filter(departement_id=periode.departement)
        qs = (qs.annotate(
            vues_vitrine=_compte(vues), appels=_compte(evts.filter(type='appel_partenaire')),
            whatsapp=_compte(evts.filter(type='whatsapp_partenaire')),
            itineraires=_compte(evts.filter(type='itineraire_partenaire')), commandes=_compte(cmd))
            .annotate(contacts=F('appels') + F('whatsapp') + F('itineraires'))
            .filter(Q(vues_vitrine__gt=0) | Q(contacts__gt=0) | Q(commandes__gt=0))
            .annotate(taux_contact_commande=Cast('commandes', FloatField()) / NullIf(F('contacts'), 0),
                      taux_vue_contact=Cast('contacts', FloatField()) / NullIf(F('vues_vitrine'), 0)))
        champ = tri.lstrip('-')
        ordre = F(champ).desc(nulls_last=True) if tri.startswith('-') else F(champ).asc(nulls_last=True)
        qs = qs.order_by(ordre, 'nom_commerce', 'id')
        total = qs.count()
        lignes = qs.values('id', 'nom_commerce', 'type_partenaire', 'departement_id', 'vues_vitrine', 'appels',
                           'whatsapp', 'itineraires', 'contacts', 'commandes', 'taux_contact_commande',
                           'taux_vue_contact')[(page - 1) * taille: page * taille]
        resultats = [{**l, 'taux_contact_commande': None if l['taux_contact_commande'] is None
                      else round(l['taux_contact_commande'], 4),
                      'taux_vue_contact': None if l['taux_vue_contact'] is None else round(l['taux_vue_contact'], 4)}
                     for l in lignes]
        return {'count': total, 'page': page, 'page_size': taille, 'tri': tri, 'resultats': resultats}


# ═══════════════════════════════════════════════════════════════════════
# 4. Activité (séries par jour, heures et jours de pointe)
# ═══════════════════════════════════════════════════════════════════════

SOURCES = ('recherches', 'evenements', 'commandes')


class ActiviteUsageView(_Vue):

    def calculer(self, periode, request):
        sources = {'recherches': (periode.recherches(), 'cree_le'),
                   'evenements': (periode.evenements(), 'cree_le'),
                   'commandes': (periode.commandes(), 'created_at')}
        jours, heures, semaine = {}, {}, {}
        for nom, (qs, champ) in sources.items():
            jours[nom] = {l['j']: l['n'] for l in qs.annotate(j=TruncDate(champ)).values('j')
                          .annotate(n=Count('id')).order_by()}
            heures[nom] = {l['h']: l['n'] for l in qs.annotate(h=ExtractHour(champ)).values('h')
                           .annotate(n=Count('id')).order_by()}
            semaine[nom] = {l['d']: l['n'] for l in qs.annotate(d=ExtractIsoWeekDay(champ)).values('d')
                            .annotate(n=Count('id')).order_by()}

        def ligne(cle, donnees, **extra):
            valeurs = {nom: donnees[nom].get(cle, 0) for nom in SOURCES}
            return {**extra, **valeurs, 'total': sum(valeurs.values())}

        par_heure = [ligne(h, heures, heure=h) for h in range(24)]
        par_jour_semaine = [ligne(d, semaine, jour=d, libelle=JOURS_SEMAINE[d]) for d in range(1, 8)]
        pointe = sorted((l for l in par_heure if l['total']), key=lambda l: (-l['total'], l['heure']))[:3]
        jour_pointe = max(par_jour_semaine, key=lambda l: (l['total'], -l['jour']))
        return {
            'par_jour': [ligne(j, jours, date=j.isoformat()) for j in periode.jours()],
            'par_heure': par_heure,
            'par_jour_semaine': par_jour_semaine,
            'heures_de_pointe': [l['heure'] for l in pointe],
            'jour_de_pointe': jour_pointe['libelle'] if jour_pointe['total'] else None,
        }


# ═══════════════════════════════════════════════════════════════════════
# 5. Résumé et comparaison avec la période précédente
# ═══════════════════════════════════════════════════════════════════════

def indicateurs(periode):
    r = periode.recherches().aggregate(
        nb=Count('id'), sans=Count('id', filter=Q(nb_resultats=0)), clics=Count('id', filter=Q(clique_le__isnull=False)))
    evts = periode.evenements()
    e = evts.aggregate(nb=Count('id'), ajouts=Count('id', filter=Q(type='panier_ajout')),
                       contacts=Count('id', filter=Q(type__in=CONTACTS)))
    c = periode.commandes().aggregate(
        nb=Count('id'), livrees=Count('id', filter=Q(statut='livree')),
        annulees=Count('id', filter=Q(statut='annulee')),
        montant=Coalesce(Sum('total', filter=Q(statut='livree')), Value(Decimal(0)), output_field=DecimalField()))
    paniers = paniers_distincts(evts)
    return {
        'nb_recherches': r['nb'],
        'nb_recherches_sans_resultat': r['sans'],
        'taux_clic_recherche': taux(r['clics'], r['nb']),
        'nb_evenements': e['nb'],
        'nb_ajouts_panier': e['ajouts'],
        'nb_paniers_avec_ajout': paniers,
        'nb_contacts_partenaires': e['contacts'],
        'nb_vues_vitrine': periode.vues_vitrine().count(),
        'nb_vues_article': periode.vues_article().count(),
        'nb_commandes': c['nb'],
        'nb_commandes_livrees': c['livrees'],
        'nb_commandes_annulees': c['annulees'],
        'montant_livre': int(c['montant'] or 0),
        'taux_conversion': taux(c['nb'], paniers),
    }


def evolution(valeur, precedente):
    """Variation relative (ratio, 4 décimales) ; null si la précédente est 0 / null."""
    if valeur is None or not precedente:
        return None
    return round((valeur - precedente) / precedente, 4)


class ResumeUsageView(_Vue):

    def calculer(self, periode, request):
        avant = periode.precedente()
        actuel, precedent = indicateurs(periode), indicateurs(avant)
        return {
            'periode_precedente': avant.en_dict(),
            'indicateurs': {cle: {'valeur': v, 'precedente': precedent[cle], 'evolution': evolution(v, precedent[cle])}
                            for cle, v in actuel.items()},
        }
