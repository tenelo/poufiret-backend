"""WhatsApp externe d'un partenaire : bouton vers son vrai WhatsApp (en plus
de la messagerie interne), affiché seulement s'il l'a activé."""
import re


def normaliser_whatsapp(brut):
    """Numéro au format international sans « + » ni espaces (wa.me) :
    « 07 07 07 07 07 » / « +225 0707070707 » / « 002250707070707 » →
    « 2250707070707 ». Numéro local ivoirien à 10 chiffres (0XXXXXXXXX) :
    indicatif 225 ajouté. None si le numéro est vide ou trop court."""
    chiffres = re.sub(r'\D', '', str(brut or ''))
    if chiffres.startswith('00'):
        chiffres = chiffres[2:]
    if re.fullmatch(r'0\d{9}', chiffres):
        chiffres = '225' + chiffres
    return chiffres if len(chiffres) >= 11 else None


def whatsapp_externe(partenaire):
    """Valeur publique : numéro normalisé si whatsapp_externe_actif et
    whatsapp renseigné (et exploitable), sinon None."""
    if partenaire is None or not getattr(partenaire, 'whatsapp_externe_actif', False):
        return None
    return normaliser_whatsapp(partenaire.whatsapp)


MESSAGE_SANS_NUMERO = ('Renseignez un numéro WhatsApp valide (ex. 07 07 07 07 07) '
                       'pour activer le bouton WhatsApp.')


def erreurs_activation(attrs, profil):
    """Règle d'écriture : bouton actif ⇒ numéro WhatsApp exploitable. Valeurs
    envoyées, sinon celles du profil. {'whatsapp': [message]} ou {}."""
    actif = attrs.get('whatsapp_externe_actif', getattr(profil, 'whatsapp_externe_actif', False))
    numero = attrs['whatsapp'] if 'whatsapp' in attrs else getattr(profil, 'whatsapp', '')
    if actif and normaliser_whatsapp(numero) is None:
        return {'whatsapp': [MESSAGE_SANS_NUMERO]}
    return {}
