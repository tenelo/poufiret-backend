"""Notification.canal / cible (additifs) + type intervention_nouvelle,
et remplissage des notifications existantes (même calcul qu'à l'émission :
apps.notifications.canaux, fonctions pures)."""
from django.db import migrations, models

from apps.notifications.canaux import TYPES_COMMANDE_RESTAURANT, canal_de, cible_depuis_data

CLES = ['commande_id', 'intervention_id', 'demande_id', 'publicite_id']
TYPES_RESTAURATION = ['restaurateur']  # apps.restaurants.services.TYPES_RESTAURATION à cette date


def remplir(apps, schema_editor):
    Notification = apps.get_model('moderation', 'Notification')
    Commande = apps.get_model('orders', 'Commande')
    Categorie = apps.get_model('catalog', 'Categorie')

    cats_resto = [c.id for c in Categorie.objects.all()
                  if set(TYPES_RESTAURATION) & set(c.types_partenaire or [])]
    ids_commandes = set()
    for data in (Notification.objects.filter(type__in=TYPES_COMMANDE_RESTAURANT)
                 .values_list('data', flat=True)):
        try:
            ids_commandes.add(int((data or {}).get('commande_id')))
        except (TypeError, ValueError):
            pass
    resto = set(Commande.objects.filter(id__in=ids_commandes).filter(
        models.Q(partenaire__type_partenaire__in=TYPES_RESTAURATION)
        | models.Q(categorie_id__in=cats_resto)).values_list('id', flat=True))

    lot, n = [], 0
    for notif in (Notification.objects.filter(data__has_any_keys=CLES)
                  .only('id', 'type', 'data').iterator(chunk_size=2000)):
        data = notif.data or {}
        try:
            est_resto = int(data.get('commande_id')) in resto
        except (TypeError, ValueError):
            est_resto = False
        notif.canal = canal_de(notif.type, est_resto)
        notif.cible = cible_depuis_data(data)
        lot.append(notif)
        if len(lot) >= 2000:
            Notification.objects.bulk_update(lot, ['canal', 'cible'])
            n += len(lot)
            lot = []
    Notification.objects.bulk_update(lot, ['canal', 'cible'])
    n += len(lot)
    print(f'\n  Notifications : canal/cible remplis pour {n} ligne(s) '
          f'(dont commandes restaurant : {len(resto)} commande(s)).')


class Migration(migrations.Migration):

    dependencies = [
        ('moderation', '0006_locations_m1'),
        ('orders', '0007_commande_categorie'),
        ('catalog', '0016_locations_v2'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='type',
            field=models.CharField(choices=[('commande_nouvelle', 'Nouvelle commande'), ('commande_acceptee', 'Commande acceptée'), ('commande_refusee', 'Commande refusée'), ('commande_prete', 'Commande prête'), ('commande_livree', 'Commande livrée'), ('nouveau_message', 'Nouveau message'), ('demande_intervention', "Demande d'intervention"), ('intervention_acceptee', 'Intervention acceptée'), ('nouveau_commentaire', 'Nouveau commentaire'), ('nouveau_like', 'Nouveau like'), ('faveur_accordee', 'Faveur accordée'), ('abonnement_expire', 'Abonnement expirant'), ('signalement_traite', 'Signalement traité'), ('systeme', 'Message système'), ('pub_soumise', 'Campagne pub soumise'), ('pub_a_valider', 'Campagne pub à valider'), ('commande_annulee_client', 'Commande annulée par le client'), ('compte_telephone_modifie', 'Numéro de connexion modifié'), ('reservation_nouvelle', 'Nouvelle demande (visite/réservation)'), ('intervention_nouvelle', "Nouvelle demande d'intervention")], max_length=40, verbose_name='type'),
        ),
        migrations.AddField(
            model_name='notification',
            name='canal',
            field=models.CharField(choices=[('restaurant', 'Restaurant'), ('general', 'Général')], default='general', max_length=20, verbose_name='canal'),
        ),
        migrations.AddField(
            model_name='notification',
            name='cible',
            field=models.JSONField(blank=True, null=True, verbose_name='cible'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', 'lu', 'canal'], name='notif_user_lu_canal_idx'),
        ),
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
