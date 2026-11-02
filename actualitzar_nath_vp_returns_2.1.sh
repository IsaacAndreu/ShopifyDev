#!/usr/bin/env bash
set -euo pipefail

# Actualitza nath_vp_returns 13.0.0.2.0 -> 13.0.0.2.1.
# 1) Comprova el paquet (Python, XML, versió).
# 2) Fa còpia de la versió instal·lada i la substitueix.
# 3) Si ho confirmes: odoo-bin -u amb el servei en marxa (--no-http, sense crons).
# 4) Si ho confirmes: systemctl restart (mai stop/start separat).
#
# Ús:
#   sudo bash actualitzar_nath_vp_returns_2.1.sh /home/it_nath_group/nath_vp_returns_13.0.0.2.1.tar.gz

ARCHIVE="${1:-}"
ADDONS="${ADDONS:-/opt/tuctuc-erp/nath/custom_addons}"
SERVICE="${SERVICE:-tuctuc-erp.service}"
DB_NAME="${DB_NAME:-TUCTUC_PRODUCTION}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"
ODOO_BIN="${ODOO_BIN:-/opt/tuctuc-erp/odoo13/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/opt/tuctuc-erp/tuctuc-erp.conf}"
ODOO_USER="${ODOO_USER:-ubuntu}"

MODULE_NAME="nath_vp_returns"
EXPECTED_VERSION="13.0.0.2.1"
TARGET="$ADDONS/$MODULE_NAME"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Falta l'arxiu .tar.gz"
[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -d "$TARGET" ]] || die "No existeix $TARGET (aquest script només actualitza)"

TMP_DIR="$(mktemp -d /tmp/vp_returns_update.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT
tar -xzf "$ARCHIVE" -C "$TMP_DIR"
MANIFEST="$(find "$TMP_DIR" -type f -path "*/${MODULE_NAME}/__manifest__.py" -print -quit)"
[[ -n "$MANIFEST" ]] || die "L'arxiu no conté ${MODULE_NAME}/__manifest__.py"
MODULE_ROOT="$(dirname "$MANIFEST")"

mapfile -t PY_FILES < <(find "$MODULE_ROOT" -type f -name '*.py' -print)
"$PYTHON" -m py_compile "${PY_FILES[@]}"
find "$MODULE_ROOT" -name __pycache__ -type d -prune -exec rm -rf {} +
mapfile -t XML_FILES < <(find "$MODULE_ROOT" -type f -name '*.xml' -print)
"$PYTHON" -c 'import sys, xml.etree.ElementTree as ET; [ET.parse(p) for p in sys.argv[1:]]' "${XML_FILES[@]}"
"$PYTHON" -c "import ast,sys; v=ast.literal_eval(open(sys.argv[1]).read())['version']; sys.exit(0 if v==sys.argv[2] else 'Versió inesperada: '+v)" \
  "$MANIFEST" "$EXPECTED_VERSION"

OWNER="$(stat -c '%u:%g' "$TARGET")"
BACKUP_DIR="$(dirname "$ADDONS")/addons_backups"   # fora de custom_addons perquè Odoo no la llegeixi
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/${MODULE_NAME}.$(date +%Y%m%d_%H%M%S)"
echo "=== ACTUALITZACIÓ $MODULE_NAME -> $EXPECTED_VERSION ==="
echo "Destí: $TARGET   Còpia: $BACKUP   BD: $DB_NAME   Servei: $SERVICE"
mv "$TARGET" "$BACKUP"
cp -a "$MODULE_ROOT" "$TARGET"
chown -R "$OWNER" "$TARGET"
echo "Codi substituït."

echo
read -r -p "Actualitzar el mòdul a $DB_NAME ara (odoo-bin -u, el servei continua en marxa)? [s/N] " OK || true
case "${OK,,}" in
  s|si|sí|y|yes)
    sudo -u "$ODOO_USER" "$PYTHON" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB_NAME" \
      -u "$MODULE_NAME" --stop-after-init --no-http --max-cron-threads=0
    echo "ACTUALITZACIÓ OK."
    ;;
  *)
    echo "No s'ha actualitzat. Per desfer la còpia: rm -rf $TARGET && mv $BACKUP $TARGET"
    exit 0
    ;;
esac

echo
read -r -p "Reiniciar $SERVICE ara (perquè tots els workers carreguin el codi nou)? [s/N] " RS || true
case "${RS,,}" in
  s|si|sí|y|yes) systemctl restart "$SERVICE"; echo "RESTART OK." ;;
  *) echo "Recorda: sudo systemctl restart $SERVICE" ;;
esac
echo "PROCÉS OK. Després del restart, revisar que no hagin quedat jobs en 'started'."
