"""Notification.canal : ajout de « service » (cloche Services), libellés
Restaurants / Services / Autres (valeurs restaurant / general gardées),
et reclassement des notifications existantes avec la règle unique
apps.notifications.canaux.canal_notification :
- interventions et réservations -> service ;
- commandes (commande_nouvelle / commande_annulee_client) de
  boulangers -> restaurant (et restauration : restaurateur, fast_food,
  grilleur — déjà restaurant à l'émission).
Seuls les canaux qui changent sont écrits ; une commande déjà classée
restaurant n'est jamais rétrogradée."""
from django.db import migrations, models

from apps.notifications.canaux import (
    CANAL_RESTAURANT, CANAL_SERVICE, CLES_SERVICE, TYPES_COMMANDE_RESTAURANT,
    TYPES_SERVICE, canal_notification,
)

# Figé à cette date : TYPES_RESTAURATION (restaurateur, fast_food, grilleur)
# + boulanger (apps.notifications.canaux.types_canal_restaurant).
TYPES_CANAL_RESTAURANT = ['restaurateur', 'fast_food', 'grilleur', 'boulanger']


def _ids_commandes_restaurant(Notification, Commande, Categorie):
    cats = [c.id for c in Categorie.objects.all()
            if set(TYPES_CANAL_RESTAURANT) & set(c.types_partenaire or [])]
    ids = set()
    for data in (Notification.objects.filter(type__in=TYPES_COMMANDE_RESTAURANT)
                 .values_list('data', flat=True)):
        try:
            ids.add(int((data or {}).get('commande_id')))
        except (TypeError, ValueError):
            pass
    return set(Commande.objects.filter(id__in=ids).filter(
        models.Q(partenaire__type_partenaire__in=TYPES_CANAL_RESTAURANT)
        | models.Q(categorie_id__in=cats)).values_list('id', flat=True))


def reclasser(apps, schema_editor):
    Notification = apps.get_model('moderation', 'Notification')
    Commande = apps.get_model('orders', 'Commande')
    Categorie = apps.get_model('catalog', 'Categorie')

    resto = _ids_commandes_restaurant(Notification, Commande, Categorie)
    qs = Notification.objects.filter(
        models.Q(type__in=list(TYPES_COMMANDE_RESTAURANT) + list(TYPES_SERVICE))
        | models.Q(data__has_any_keys=list(CLES_SERVICE)))

    lot, nb = [], {CANAL_SERVICE: 0, CANAL_RESTAURANT: 0}
    for notif in qs.only('id', 'type', 'data', 'canal').iterator(chunk_size=2000):
        data = notif.data or {}
        est_resto = None
        if notif.type in TYPES_COMMANDE_RESTAURANT:
            try:
                est_resto = int(data.get('commande_id')) in resto
            except (TypeError, ValueError):
                est_resto = False
        canal = canal_notification(notif.type, data, est_restaurant=est_resto)
        if canal == notif.canal or (notif.canal == CANAL_RESTAURANT and canal != CANAL_SERVICE):
            continue
        notif.canal = canal
        lot.append(notif)
        nb[canal] = nb.get(canal, 0) + 1
        if len(lot) >= 2000:
            Notification.objects.bulk_update(lot, ['canal'])
            lot = []
    Notification.objects.bulk_update(lot, ['canal'])
    print(f'\n  Notifications reclassées : {nb[CANAL_SERVICE]} -> service, '
          f'{nb[CANAL_RESTAURANT]} -> restaurant.')


def annuler(apps, schema_editor):
    """Retour arrière : service -> general (canal absent avant 0008)."""
    apps.get_model('moderation', 'Notification').objects.filter(
        canal=CANAL_SERVICE).update(canal='general')


class Migration(migrations.Migration):

    dependencies = [
        ('moderation', '0007_notification_canal_cible'),
        ('orders', '0009_commande_created_at_idx'),
        ('catalog', '0024_variante_image'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='canal',
            field=models.CharField(choices=[('restaurant', 'Restaurants'), ('service', 'Services'), ('general', 'Autres')], default='general', max_length=20, verbose_name='canal'),
        ),
        migrations.RunPython(reclasser, annuler),
    ]
