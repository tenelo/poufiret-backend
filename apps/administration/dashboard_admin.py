"""Page 'Tableau de bord' dans le Django admin (super-admin only).

Affiche les compteurs déjà calculés par analytics.stats_connexion :
en ligne maintenant, comptes créés, connexions distinctes (jour/semaine/
mois), le tout ventilé par rôle. Réutilise tableau_de_bord() — aucune
logique dupliquée.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.http import HttpResponseForbidden


@staff_member_required
def vue_tableau_de_bord(request):
    u = request.user
    a_le_droit = u.is_superuser or (
        u.is_staff and getattr(
            getattr(u, 'permissions_admin', None), 'voir_stats', False))
    if not a_le_droit:
        return HttpResponseForbidden(
            "Accès réservé : cochez « voir les stats » pour cet admin.")
    from apps.analytics.stats_connexion import tableau_de_bord
    from apps.administration import services

    data = tableau_de_bord()
    data['appareils'] = services.repartition_appareils()
    contexte = {
        'title': 'Tableau de bord',
        'data': data,
        'en_ligne': data['en_ligne'],
        'comptes': data['comptes'],
        'connexions': data['connexions_distinctes'],
        'appareils': data['appareils'],
    }
    return render(request, 'admin/tableau_de_bord.html', contexte)
