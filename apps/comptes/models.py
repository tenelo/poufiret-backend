"""Modèles proxy regroupés dans le bloc « COMPTES » du Django admin.

Aucune table créée : ce sont des vues proxy de User, filtrées par rôle
côté admin. Le but est purement l'organisation du menu (bloc COMPTES
séparé de USERS, qui garde Adresses / Plans / Profils / Horaires).
"""
from apps.users.models import User


class Client(User):
    class Meta:
        proxy = True
        app_label = 'comptes'
        verbose_name = 'client'
        verbose_name_plural = 'Clients'


class Partenaire(User):
    class Meta:
        proxy = True
        app_label = 'comptes'
        verbose_name = 'partenaire'
        verbose_name_plural = 'Partenaires'


class Administrateur(User):
    class Meta:
        proxy = True
        app_label = 'comptes'
        verbose_name = 'admin'
        verbose_name_plural = 'Admins'


class Livreur(User):
    class Meta:
        proxy = True
        app_label = 'comptes'
        verbose_name = 'livreur'
        verbose_name_plural = 'Livreurs'
