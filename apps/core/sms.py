"""
Couche d'envoi SMS abstraite pour Poufiret.

But : le code metier (OTP, notifications) appelle UNIQUEMENT `envoyer_sms(...)`
sans jamais savoir quel fournisseur est derriere. Basculer du mode faux-SMS
(dev, gratuit) vers un vrai fournisseur (Orange / Twilio / MTN) se fait en
changeant UNE ligne de config : `SMS_BACKEND` dans settings. Aucun code metier
a reecrire.

Ajouter un vrai fournisseur plus tard =
  1. ecrire une classe qui herite de EnvoyeurSMS et implemente `envoyer`
  2. l'enregistrer dans BACKENDS ci-dessous
  3. pointer SMS_BACKEND dessus dans settings
"""
import logging
from abc import ABC, abstractmethod

from django.conf import settings

logger = logging.getLogger('poufiret.sms')


class ResultatSMS:
    """Retour standardise d'un envoi, quel que soit le fournisseur."""
    def __init__(self, succes, fournisseur, detail=''):
        self.succes = succes
        self.fournisseur = fournisseur
        self.detail = detail

    def __bool__(self):
        return self.succes

    def __repr__(self):
        etat = 'OK' if self.succes else 'ECHEC'
        return f'<ResultatSMS {etat} {self.fournisseur} {self.detail!r}>'


class EnvoyeurSMS(ABC):
    """Contrat commun a tous les fournisseurs SMS."""
    nom = 'abstrait'

    @abstractmethod
    def envoyer(self, telephone, message):
        """Envoie `message` vers `telephone`. Retourne un ResultatSMS."""
        raise NotImplementedError


class FauxSMS(EnvoyeurSMS):
    """
    Mode dev : n'envoie RIEN, ecrit le SMS dans les logs.
    Gratuit, permet de developper et tester tout le flux OTP sans facture.
    """
    nom = 'faux'

    def envoyer(self, telephone, message):
        logger.info('[FAUX-SMS] vers %s : %s', telephone, message)
        return ResultatSMS(True, self.nom, detail='logue (aucun envoi reel)')


# Registre des backends disponibles. On ajoutera OrangeSMS / TwilioSMS ici.
BACKENDS = {
    'faux': FauxSMS,
}


def get_envoyeur_sms():
    """
    Renvoie l'instance d'envoyeur selon settings.SMS_BACKEND (defaut 'faux').
    Point de bascule unique dev -> prod.
    """
    cle = getattr(settings, 'SMS_BACKEND', 'faux')
    classe = BACKENDS.get(cle)
    if classe is None:
        logger.warning(
            "SMS_BACKEND=%r inconnu, repli sur 'faux'. Backends: %s",
            cle, list(BACKENDS),
        )
        classe = FauxSMS
    return classe()


def envoyer_sms(telephone, message):
    """
    Facade unique appelee par le code metier (OTP, notifs).
    Ne connait jamais le fournisseur concret.
    """
    envoyeur = get_envoyeur_sms()
    resultat = envoyeur.envoyer(telephone, message)
    if not resultat.succes:
        logger.error('Echec envoi SMS vers %s via %s : %s',
                     telephone, resultat.fournisseur, resultat.detail)
    return resultat
