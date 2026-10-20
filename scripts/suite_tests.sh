#!/bin/sh
# Suite complète : exécute chaque scripts/test_*.py dans le conteneur et
# résume « OK / FAIL » par script (non-régression, dont Chez Capi via
# test_restaurants_public.py).
#   sh scripts/suite_tests.sh                 (conteneur backend-poufiret)
#   CONTENEUR=autre sh scripts/suite_tests.sh
CONTENEUR=${CONTENEUR:-backend-poufiret}
cd "$(dirname "$0")/.." || exit 1
echec=0
for f in scripts/test_*.py; do
  sortie=$(docker exec -i "$CONTENEUR" python manage.py shell < "$f" 2>&1)
  nok=$(printf '%s\n' "$sortie" | grep -c '^OK')
  nfail=$(printf '%s\n' "$sortie" | grep -c '^FAIL')
  fin=$(printf '%s\n' "$sortie" | tail -1 | cut -c1-100)
  printf '%-48s %4s OK %3s FAIL  | %s\n' "$(basename "$f")" "$nok" "$nfail" "$fin"
  case "$fin" in *Rollback*) ;; *) echec=1 ;; esac
done
exit $echec
