"""Serializers du centre de gestion admin des commandes.

Distincts des serializers partenaire/client (apps.orders.serializers,
INCHANGÉS). Réservés à ADroitDe('gerer_commandes').
"""
from rest_framework import serializers

from apps.users.models import ProfilPartenaire

from .models import Commande, HistoriqueCommande, NoteAdminCommande
from .services import (
    ACTIONS_LIBELLES, GROUPE_PAR_STATUT, LIBELLES_GROUPE, TRANSITIONS,
)


def _nom_utilisateur(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username or user.telephone


class ClientResumeSerializer(serializers.Serializer):
    """Instanciée sur un vrai User (obj.user), comme PartenaireResumeSerializer
    sur un vrai ProfilPartenaire — pas sur un dict synthétique (un
    SerializerMethodField reçoit l'INSTANCE entière, pas la valeur du champ)."""
    id = serializers.IntegerField(source='pk')
    nom = serializers.SerializerMethodField()
    telephone = serializers.CharField()

    def get_nom(self, obj):
        return _nom_utilisateur(obj)


class PartenaireResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.CharField(source='nom_commerce')
    telephone = serializers.SerializerMethodField()
    type_partenaire = serializers.CharField()
    type_partenaire_libelle = serializers.SerializerMethodField()

    def get_telephone(self, obj):
        return obj.telephone_pro or getattr(obj.user, 'telephone', '')

    def get_type_partenaire_libelle(self, obj):
        return obj.get_type_partenaire_display()


class LivraisonResumeSerializer(serializers.Serializer):
    id = serializers.CharField()
    statut = serializers.CharField()
    statut_libelle = serializers.SerializerMethodField()
    livreur_nom = serializers.SerializerMethodField()
    livreur_telephone = serializers.SerializerMethodField()

    def get_statut_libelle(self, obj):
        return obj.get_statut_display()

    def get_livreur_nom(self, obj):
        return _nom_utilisateur(obj.livreur.user) if obj.livreur_id else None

    def get_livreur_telephone(self, obj):
        return obj.livreur.user.telephone if obj.livreur_id else None


def _course_active(commande):
    """La course en cours de cette commande (dernière non annulée/refusée),
    lue depuis le prefetch `courses_triees` posé par la vue (0 requête) —
    voir apps.orders.views_admin._commandes_admin_qs."""
    for course in getattr(commande, 'courses_triees', commande.courses.all()):
        if course.statut not in ('annulee', 'refusee'):
            return course
    return None


class CommandeAdminListSerializer(serializers.ModelSerializer):
    """Une ligne de GET /orders/admin/commandes/."""
    reference = serializers.CharField(source='numero')
    cree_le = serializers.DateTimeField(source='created_at')
    statut_libelle = serializers.SerializerMethodField()
    groupe = serializers.SerializerMethodField()
    montant_total = serializers.DecimalField(
        source='total', max_digits=12, decimal_places=0)
    nb_articles = serializers.IntegerField(read_only=True)  # annoté (Sum quantite)
    mode_livraison_libelle = serializers.SerializerMethodField()
    client = serializers.SerializerMethodField()
    partenaire = serializers.SerializerMethodField()
    departement_nom = serializers.SerializerMethodField()
    age_minutes = serializers.SerializerMethodField()
    livraison = serializers.SerializerMethodField()

    class Meta:
        model = Commande
        fields = ['id', 'reference', 'cree_le', 'statut', 'statut_libelle',
                  'groupe', 'montant_total', 'nb_articles', 'mode_livraison',
                  'mode_livraison_libelle', 'client', 'partenaire',
                  'departement_nom', 'age_minutes', 'livraison']

    def get_statut_libelle(self, obj):
        return obj.get_statut_display()

    def get_groupe(self, obj):
        return GROUPE_PAR_STATUT.get(obj.statut, '')

    def get_mode_livraison_libelle(self, obj):
        return obj.get_mode_livraison_display()

    def get_client(self, obj):
        return ClientResumeSerializer(obj.user).data

    def get_partenaire(self, obj):
        return PartenaireResumeSerializer(obj.partenaire).data

    def get_departement_nom(self, obj):
        dep = getattr(obj.partenaire, 'departement', None)
        return dep.nom if dep else ''

    def get_age_minutes(self, obj):
        from django.utils import timezone
        return int((timezone.now() - obj.created_at).total_seconds() // 60)

    def get_livraison(self, obj):
        course = _course_active(obj)
        return LivraisonResumeSerializer(course).data if course else None


class LigneCommandeAdminSerializer(serializers.Serializer):
    article_nom = serializers.CharField(source='nom_article')
    quantite = serializers.IntegerField()
    prix_unitaire = serializers.DecimalField(max_digits=12, decimal_places=0)
    sous_total = serializers.DecimalField(source='prix_ligne', max_digits=12, decimal_places=0)
    details = serializers.SerializerMethodField()

    def get_details(self, obj):
        return {
            'variante': obj.variante_nom or None,
            'supplements': obj.supplements or [],
            'note_speciale': obj.note_speciale or '',
        }


class NoteAdminCommandeSerializer(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = NoteAdminCommande
        fields = ['id', 'auteur_nom', 'texte', 'cree_le']

    def get_auteur_nom(self, obj):
        return _nom_utilisateur(obj.auteur) if obj.auteur_id else 'Système'


class HistoriqueCommandeSerializer(serializers.ModelSerializer):
    statut_libelle = serializers.SerializerMethodField()
    acteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueCommande
        fields = ['statut', 'statut_libelle', 'acteur_nom', 'acteur_role',
                  'commentaire', 'cree_le']

    def get_statut_libelle(self, obj):
        return dict(Commande.Statut.choices).get(obj.statut, obj.statut)

    def get_acteur_nom(self, obj):
        return _nom_utilisateur(obj.acteur) if obj.acteur_id else 'Système'


class CommandeAdminDetailSerializer(CommandeAdminListSerializer):
    """GET /orders/admin/commandes/<id>/ — tous les champs de la liste, plus
    lignes, adresse, notes, historique, transitions possibles."""
    lignes = serializers.SerializerMethodField()
    adresse_livraison = serializers.SerializerMethodField()
    note_client = serializers.CharField(source='notes_client')
    notes_admin = serializers.SerializerMethodField()
    historique = serializers.SerializerMethodField()
    transitions_possibles = serializers.SerializerMethodField()
    peut_demander_livreur = serializers.SerializerMethodField()

    class Meta(CommandeAdminListSerializer.Meta):
        fields = CommandeAdminListSerializer.Meta.fields + [
            'lignes', 'adresse_livraison', 'note_client', 'notes_admin',
            'historique', 'transitions_possibles', 'peut_demander_livreur',
        ]

    def get_lignes(self, obj):
        return LigneCommandeAdminSerializer(obj.lignes.all(), many=True).data

    def get_adresse_livraison(self, obj):
        if obj.mode_livraison != Commande.ModeLivraison.LIVRAISON:
            return None
        pt = obj.localisation_livraison
        return {
            'texte': obj.adresse_snapshot or '',
            'latitude': pt.y if pt else None,
            'longitude': pt.x if pt else None,
        }

    def get_notes_admin(self, obj):
        return NoteAdminCommandeSerializer(obj.notes_admin.all(), many=True).data

    def get_historique(self, obj):
        return HistoriqueCommandeSerializer(obj.historique.all(), many=True).data

    def get_transitions_possibles(self, obj):
        return [{
            'action': action,
            'libelle': ACTIONS_LIBELLES.get(action, action),
            'commentaire_obligatoire': action == Commande.Statut.ANNULEE,
        } for action in TRANSITIONS.get(obj.statut, [])]

    def get_peut_demander_livreur(self, obj):
        from .services import commande_eligible_livreur
        return commande_eligible_livreur(obj)
