"""
Migration douce AUTH : pose un PIN sur les comptes existants et les inscrit
dans NumeroVerifie (plus jamais d'OTP). Idempotent, relançable.

- Comptes nommes (Awa, Tenelo, super-admin) : PIN connu 0733, pin_par_defaut=False.
- Tout autre compte : PIN aleatoire 4 chiffres, pin_par_defaut=True.
- Tous : entree dans NumeroVerifie (source migration).
"""
import random
from apps.users.models import User, NumeroVerifie

PIN_NOMMES = "0733"
NOMMES = {
    "+2250700000002",  # Awa
    "+2250700000001",  # Tenelo
    "+2250707788481",  # super-admin Etienne
}

print("=== MIGRATION DOUCE PIN ===")
total = User.objects.count()
print(f"comptes existants : {total}\n")

for user in User.objects.all():
    tel = user.telephone
    if tel in NOMMES:
        user.set_password(PIN_NOMMES)
        user.pin_par_defaut = False
        user.est_verifie = True
        user.save(update_fields=['password', 'pin_par_defaut', 'est_verifie'])
        etiquette = f"NOMME  -> PIN {PIN_NOMMES} (pin_par_defaut=False)"
    else:
        pin = f"{random.randint(0, 9999):04d}"
        # on evite les triviaux de ton set
        while pin in {"0000", "1111", "1234"}:
            pin = f"{random.randint(0, 9999):04d}"
        user.set_password(pin)
        user.pin_par_defaut = True
        user.est_verifie = True
        user.save(update_fields=['password', 'pin_par_defaut', 'est_verifie'])
        etiquette = f"AUTRE  -> PIN aleatoire {pin} (pin_par_defaut=True, a changer)"

    obj, cree = NumeroVerifie.objects.get_or_create(
        telephone=tel,
        defaults={
            'nom': user.last_name or '',
            'prenom': user.first_name or '',
            'source': NumeroVerifie.Source.MIGRATION,
        },
    )
    reg = "ajoute au registre" if cree else "deja dans registre"
    print(f"{tel:18} | role={user.role:10} | {etiquette:55} | {reg}")

print(f"\n=== TERMINE : {total} compte(s) traite(s), NumeroVerifie a jour ===")
