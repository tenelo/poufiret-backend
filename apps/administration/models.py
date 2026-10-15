"""Modèles du bloc administration (G5).

Pour l'instant : le journal d'audit de la modération de comptes.
Chaque action de modération (suspension, bannissement, suppression,
réactivation) DOIT créer une entrée ici — traçabilité obligatoire
décidée avec Tenelo : qui, quand, quoi, sur qui, pourquoi.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone

from apps.core.models import ModeleBase


class JournalModeration(ModeleBase):
    """Trace d'audit d'une action de modération sur un compte."""

    class Action(models.TextChoices):
        SUSPENDRE = 'suspendre', 'Suspension'
        REACTIVER = 'reactiver', 'Réactivation'
        BANNIR = 'bannir', 'Bannissement'
        SUPPRIMER_SOFT = 'supprimer_soft', 'Suppression douce'
        SUPPRIMER_HARD = 'supprimer_hard', 'Suppression définitive'
        RESTAURER = 'restaurer', 'Restauration (annule suppression douce)'
        ACCORDER_FAVEUR = 'accorder_faveur', 'Octroi d\'une faveur'
        RETIRER_FAVEUR = 'retirer_faveur', 'Retrait d\'une faveur'
        ACCEPTER_PARTENAIRE = 'accepter_partenaire', 'Demande partenaire acceptée'
        REJETER_PARTENAIRE = 'rejeter_partenaire', 'Demande partenaire rejetée'
        CREER_PARTENAIRE = 'creer_partenaire', 'Création d\'un partenaire (démarcheur)'
        PUB_PAIEMENT_OK = 'pub_paiement_ok', 'Publicité : paiement confirmé'
        PUB_VALIDER = 'pub_valider', 'Publicité validée'
        PUB_REJETER = 'pub_rejeter', 'Publicité rejetée'
        PUB_TERMINER = 'pub_terminer', 'Publicité terminée'
        PUB_ANNULER = 'pub_annuler', 'Publicité : soumission annulée'
        PUB_FORMULE_CREER = 'pub_formule_creer', 'Formule pub créée'
        PUB_FORMULE_MODIF = 'pub_formule_modif', 'Formule pub modifiée'
        PUB_FORMULE_SUPPR = 'pub_formule_suppr', 'Formule pub supprimée'
        PUB_FORMULE_DESACT = 'pub_formule_desact', 'Formule pub désactivée'
        PUB_FORMULE_REACT = 'pub_formule_react', 'Formule pub réactivée'
        PUB_PARAMETRES_MAJ = 'pub_parametres_maj', 'Paramètres pub modifiés'
        PUB_STATS_VISIBLES = 'pub_stats_visibles', 'Stats pub : visibilité partenaire'
        RESTO_FICHE_MODIF = 'resto_fiche_modif', 'Fiche restaurant modifiée (admin)'
        RESTO_PLAT_MODIF = 'resto_plat_modif', 'Plat modifié (admin)'
        RESTO_MENU_MODIF = 'resto_menu_modif', 'Menu modifié (admin)'
        PARTENAIRE_TELEPHONE_MODIF = 'partenaire_telephone_modif', 'Numéro de connexion partenaire modifié'
        GEO_RAPPROCHEMENT_PARTENAIRE = 'geo_rapprochement_partenaire', 'Géographie partenaire rapprochée'
        PARTENAIRE_POSITION = 'partenaire_position', 'Position GPS partenaire modifiée'
        PARTENAIRE_EDITION = 'partenaire_edition', 'Fiche partenaire modifiée (admin)'
        LOC_LOGEMENT_MODIF = 'loc_logement_modif', 'Logement modifié (admin)'
        LOC_DISPO_MODIF = 'loc_dispo_modif', 'Disponibilité de logement modifiée (admin)'
        LOC_VEHICULE_MODIF = 'loc_vehicule_modif', 'Véhicule modifié (admin)'
        LOC_VEHICULE_DISPO = 'loc_vehicule_dispo', 'Disponibilité de véhicule modifiée (admin)'
        LOC_ETABLISSEMENT_MODIF = 'loc_etablissement_modif', 'Fiche établissement modifiée (admin)'
        LOC_HEBERGEMENT_MODIF = 'loc_hebergement_modif', 'Hébergement modifié (admin)'
        LOC_HEBERGEMENT_DISPO = 'loc_hebergement_dispo', 'Disponibilité d\'hébergement modifiée (admin)'
        CAT_CREATION = 'cat_creation', 'Catégorie créée'
        CAT_MODIFICATION = 'cat_modification', 'Catégorie modifiée'
        CAT_SUPPRESSION = 'cat_suppression', 'Catégorie supprimée'
        CAT_ARCHIVAGE = 'cat_archivage', 'Catégorie archivée'
        CAT_DESARCHIVAGE = 'cat_desarchivage', 'Catégorie désarchivée'
        PARAM_MOTS_CLES = 'param_mots_cles', 'Paramètres : mots-clés de catégorie modifiés'
        PARAM_ORDRE_CATEG = 'param_ordre_categ', 'Paramètres : ordre des catégories modifié'
        PARAM_CATEG_VISIB = 'param_categorie_visib', 'Paramètres : catégorie affichée ou masquée'
        PARAM_RECHERCHE_TRAITE = 'param_recherche_traite', 'Paramètres : terme sans résultat traité'
        PARAM_RECHERCHE_IGNORE = 'param_recherche_ignore', 'Paramètres : terme sans résultat ignoré'

    # Qui a agi (le super-admin). SET_NULL pour garder la trace même si
    # l'acteur est supprimé plus tard.
    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='actions_moderation',
        verbose_name='acteur (super-admin)',
    )
    # Sur qui. Null=True car une suppression définitive efface la cible :
    # on conserve alors son identifiant en clair dans cible_identifiant.
    cible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='moderations_subies',
        verbose_name='cible',
    )
    cible_identifiant = models.CharField(
        'identifiant de la cible', max_length=150, blank=True,
        help_text='Téléphone/identifiant conservé en clair (surtout si la '
                  'cible est supprimée définitivement).',
    )
    cible_role = models.CharField('rôle de la cible', max_length=20, blank=True)
    action = models.CharField('action', max_length=30, choices=Action.choices)
    motif = models.CharField('motif', max_length=255, blank=True)
    # Regroupement des entrées identiques rapprochées (voir enregistrer()).
    occurrences = models.PositiveIntegerField('occurrences', default=1)
    derniere_occurrence = models.DateTimeField(
        'dernière occurrence', blank=True, null=True,
        help_text='Date de la dernière occurrence regroupée (= cree_le si une seule).')

    # Fenêtre de regroupement : une entrée IDENTIQUE (même acteur, même
    # action, même cible, même motif) créée moins de 10 min après la
    # précédente incrémente `occurrences` au lieu de créer une ligne.
    FENETRE_REGROUPEMENT = timedelta(minutes=10)

    class Meta:
        verbose_name = 'entrée de journal de modération'
        verbose_name_plural = 'journal de modération'
        ordering = ['-cree_le']
        indexes = [
            models.Index(fields=['cible', 'cree_le']),
            models.Index(fields=['action', 'cree_le']),
            # Liste du journal (tri -cree_le, [:200]) et purge par date.
            models.Index(fields=['-cree_le'], name='journal_cree_le_idx'),
            # Recherche de l'entrée à regrouper.
            models.Index(fields=['acteur', 'action', '-derniere_occurrence'],
                         name='journal_regroupement_idx'),
        ]

    @classmethod
    def enregistrer(cls, acteur, cible, action, motif='', cible_identifiant=None, cible_role=None):
        """Point d'écriture unique du journal, avec regroupement des seules
        entrées strictement identiques (motif compris).

        Le motif fait partie de l'identité : il porte le contenu de
        l'action (ex. « ancien → nouveau » d'un changement de numéro, lu
        par l'historique téléphone). Regrouper des motifs différents
        effacerait ce contenu — seules les répétitions exactes (ex. même
        plat ré-enregistré) sont factorisées."""
        maintenant = timezone.now()
        motif = (motif or '')[:255]
        if cible_identifiant is None:
            cible_identifiant = getattr(cible, 'telephone', '') if cible else ''
        if cible_role is None:
            cible_role = getattr(cible, 'role', '') if cible else ''
        filtre = {'acteur': acteur, 'action': action, 'motif': motif,
                  'derniere_occurrence__gte': maintenant - cls.FENETRE_REGROUPEMENT}
        if cible is not None:
            filtre['cible'] = cible
        else:
            filtre.update(cible__isnull=True, cible_identifiant=cible_identifiant)
        precedente = cls.objects.filter(**filtre).order_by('-derniere_occurrence').first()
        if precedente is not None:
            cls.objects.filter(pk=precedente.pk).update(
                occurrences=F('occurrences') + 1, derniere_occurrence=maintenant,
                modifie_le=maintenant)
            precedente.refresh_from_db()
            return precedente
        return cls.objects.create(
            acteur=acteur, cible=cible, cible_identifiant=cible_identifiant,
            cible_role=cible_role, action=action, motif=motif,
            derniere_occurrence=maintenant)

    def __str__(self):
        return (f'{self.get_action_display()} — {self.cible_identifiant} '
                f'par {self.acteur} ({self.cree_le:%d/%m/%Y %H:%M})')


class PermissionsAdmin(ModeleBase):
    """Permissions granulaires d'un compte admin (is_staff, non super-admin).

    Le super-admin (is_superuser) ignore ces cases : il peut tout.
    Un admin ne peut faire QUE ce qui est coché ici. Par défaut : rien.

    La modération de comptes se décline par rôle cible (client / partenaire
    / admin) : ex. un admin peut avoir le droit de suspendre des clients
    mais pas des admins.
    """
    admin = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='permissions_admin', verbose_name='compte admin',
    )

    # ── A. Modération de comptes (× client / partenaire / admin) ─────
    # suspendre
    suspendre_client = models.BooleanField('suspendre — clients', default=False)
    suspendre_partenaire = models.BooleanField('suspendre — partenaires', default=False)
    suspendre_admin = models.BooleanField('suspendre — admins', default=False)
    # reactiver
    reactiver_client = models.BooleanField('réactiver — clients', default=False)
    reactiver_partenaire = models.BooleanField('réactiver — partenaires', default=False)
    reactiver_admin = models.BooleanField('réactiver — admins', default=False)
    # bannir
    bannir_client = models.BooleanField('bannir — clients', default=False)
    bannir_partenaire = models.BooleanField('bannir — partenaires', default=False)
    bannir_admin = models.BooleanField('bannir — admins', default=False)
    # supprimer douce
    supprimer_soft_client = models.BooleanField('supprimer (douce) — clients', default=False)
    supprimer_soft_partenaire = models.BooleanField('supprimer (douce) — partenaires', default=False)
    supprimer_soft_admin = models.BooleanField('supprimer (douce) — admins', default=False)
    # supprimer definitive
    supprimer_hard_client = models.BooleanField('supprimer (définitive) — clients', default=False)
    supprimer_hard_partenaire = models.BooleanField('supprimer (définitive) — partenaires', default=False)
    supprimer_hard_admin = models.BooleanField('supprimer (définitive) — admins', default=False)
    # restaurer
    restaurer_client = models.BooleanField('restaurer — clients', default=False)
    restaurer_partenaire = models.BooleanField('restaurer — partenaires', default=False)
    restaurer_admin = models.BooleanField('restaurer — admins', default=False)

    # ── B. Partenaires ───────────────────────────────────────────────
    masquer_partenaire = models.BooleanField('masquer / afficher un partenaire', default=False)
    certifier_partenaire = models.BooleanField('donner / retirer le badge certifié', default=False)
    accorder_faveur = models.BooleanField('accorder / retirer une faveur', default=False)
    valider_devenir_partenaire = models.BooleanField('valider une demande « devenir partenaire »', default=False)
    creer_partenaire = models.BooleanField('créer un partenaire de A à Z (démarcheur)', default=False)

    # ── C. Publicités ────────────────────────────────────────────────
    valider_publicite = models.BooleanField('valider / rejeter une publicité', default=False)
    offrir_campagne = models.BooleanField('offrir / retirer une campagne', default=False)

    # ── D. Commandes & paiements ─────────────────────────────────────
    valider_commande = models.BooleanField('valider / rejeter une commande', default=False)
    valider_paiement = models.BooleanField('valider / rejeter un paiement', default=False)

    # ── E. Configuration ─────────────────────────────────────────────
    modifier_plans_formules = models.BooleanField('modifier les plans et formules', default=False)

    # ── F. Consultation & données ────────────────────────────────────
    voir_stats = models.BooleanField('voir les stats', default=False)
    voir_indicateurs = models.BooleanField('voir les indicateurs partenaires', default=False)
    voir_interventions = models.BooleanField(
        'voir les demandes d\'intervention (tous artisans)', default=False)
    lire_journal = models.BooleanField('lire le journal d\'audit', default=False)
    exporter_csv = models.BooleanField('exporter en CSV', default=False)

    # ── G. Gestion ────────────────────────────────────────────────────
    gerer_admins = models.BooleanField(
        'gérer les comptes admins (créer, éditer capacités, révoquer)',
        default=False,
    )
    gerer_geographie = models.BooleanField(
        'gérer la géographie (régions, départements, localités, quartiers)',
        default=False,
    )
    gerer_formules_pub = models.BooleanField(
        'gérer les formules et paramètres de publicité',
        default=False,
    )
    gerer_commandes = models.BooleanField(
        'gérer les commandes (centre de gestion admin)',
        default=False,
    )
    gerer_restaurants = models.BooleanField(
        'gérer les restaurants (fiche, carte, menus) à la place du restaurateur',
        default=False,
    )
    modifier_identifiant_partenaire = models.BooleanField(
        'modifier le numéro de connexion d\'un partenaire',
        default=False,
    )
    gerer_parametres = models.BooleanField(
        'gérer les paramètres (dictionnaire de recherche, ordre des catégories)',
        default=False,
    )
    gerer_locations = models.BooleanField(
        'gérer les locations (logements, véhicules, hébergements) à la place du loueur',
        default=False,
    )
    gerer_reservations = models.BooleanField(
        "gérer le centre de demandes (visite/réservation)",
        default=False,
    )
    gerer_interventions = models.BooleanField(
        "gérer les demandes d'intervention (écriture ; implique la lecture)",
        default=False,
    )

    class Meta:
        verbose_name = 'permissions admin'
        verbose_name_plural = 'permissions des admins'

    def __str__(self):
        return f'Permissions de {self.admin}'



class ConnexionAdmin(models.Model):
    """Suivi des connexions d'un compte admin : UNE ligne par admin, mise à
    jour à chaque connexion (pas de nouvelle ligne) — alimente la liste
    /administration/connexions-admin/. Les sessions par appareil restent
    dans users.SessionAppareil (révocation ciblée, « mes appareils »)."""
    admin = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='connexion_admin', verbose_name='compte admin',
    )
    premiere_connexion = models.DateTimeField('première connexion')
    derniere_connexion = models.DateTimeField('dernière connexion', db_index=True)
    nb_connexions = models.PositiveIntegerField('nombre de connexions', default=1)
    derniere_ip = models.GenericIPAddressField('dernière adresse IP', blank=True, null=True)
    dernier_appareil = models.CharField(
        'dernier appareil (user agent)', max_length=500, blank=True)
    derniere_plateforme = models.CharField('dernière plateforme', max_length=10, blank=True)

    class Meta:
        verbose_name = 'connexion admin'
        verbose_name_plural = 'connexions admin'
        ordering = ['-derniere_connexion']

    def __str__(self):
        return f'{self.admin} — {self.nb_connexions} connexion(s)'

    @classmethod
    def enregistrer(cls, user, ip=None, user_agent='', plateforme=''):
        """Compte une connexion (admins is_staff uniquement) : crée la ligne
        à la première, sinon l'incrémente atomiquement."""
        if not (user and user.is_staff):
            return None
        maintenant = timezone.now()
        valeurs = {'derniere_connexion': maintenant, 'derniere_ip': ip or None,
                   'dernier_appareil': (user_agent or '')[:500],
                   'derniere_plateforme': (plateforme or '')[:10]}
        n = cls.objects.filter(admin=user).update(nb_connexions=F('nb_connexions') + 1, **valeurs)
        if n == 0:
            from django.db import IntegrityError, transaction
            try:
                with transaction.atomic():
                    cls.objects.create(admin=user, premiere_connexion=maintenant,
                                       nb_connexions=1, **valeurs)
            except IntegrityError:  # connexion concurrente : la ligne existe déjà
                cls.objects.filter(admin=user).update(
                    nb_connexions=F('nb_connexions') + 1, **valeurs)
        return cls.objects.get(admin=user)
