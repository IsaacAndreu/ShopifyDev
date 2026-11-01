#!/usr/bin/env bash
set -euo pipefail

# Instal·la el mòdul NOU nath_vp_returns (Devoluciones VP, pilot de consulta).
# 1) Comprova el paquet (Python, XML, versió) i que hi hagi requests.
# 2) El copia a custom_addons (no pot existir encara).
# 3) Si ho confirmes: odoo-bin -i amb el servei en marxa (--no-http, sense crons).
# 4) Si ho confirmes: systemctl restart (mai stop/start separat).
# En instal·lar-se no fa res sol: no té cron ni escriu a PinkConnect.
#
# Ús:
#   sudo bash install_nath_vp_returns.sh /home/it_nath_group/nath_vp_returns_13.0.0.1.3.tar.gz

ARCHIVE="${1:-}"
ADDONS="${ADDONS:-/opt/tuctuc-erp/nath/custom_addons}"
SERVICE="${SERVICE:-tuctuc-erp.service}"
DB_NAME="${DB_NAME:-TUCTUC_PRODUCTION}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"
ODOO_BIN="${ODOO_BIN:-/opt/tuctuc-erp/odoo13/odoo-bin}"
ODOO_CONF="${ODOO_CONF:-/opt/tuctuc-erp/tuctuc-erp.conf}"
ODOO_USER="${ODOO_USER:-ubuntu}"

MODULE_NAME="nath_vp_returns"
EXPECTED_VERSION="13.0.0.1.3"
TARGET="$ADDONS/$MODULE_NAME"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Falta l'arxiu .tar.gz"
[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -d "$ADDONS" ]] || die "No existeix $ADDONS"
[[ ! -e "$TARGET" ]] || die "Ja existeix $TARGET (aquest script només instal·la la primera vegada)"

TMP_DIR="$(mktemp -d /tmp/vp_returns_install.XXXXXX)"
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
"$PYTHON" -c "import requests" || die "Falta la llibreria requests"

OWNER="$(stat -c '%u:%g' "$ADDONS/nath_shopify_returns" 2>/dev/null || stat -c '%u:%g' "$ADDONS")"
echo "=== INSTAL·LACIÓ $MODULE_NAME $EXPECTED_VERSION ==="
echo "Destí: $TARGET   Propietari: $OWNER   BD: $DB_NAME   Servei: $SERVICE"
cp -a "$MODULE_ROOT" "$TARGET"
chown -R "$OWNER" "$TARGET"
echo "Còpia feta."

echo
read -r -p "Instal·lar el mòdul a $DB_NAME ara (odoo-bin -i, el servei continua en marxa)? [s/N] " OK || true
case "${OK,,}" in
  s|si|sí|y|yes)
    sudo -u "$ODOO_USER" "$PYTHON" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB_NAME" \
      -i "$MODULE_NAME" --stop-after-init --no-http --max-cron-threads=0
    echo "INSTAL·LACIÓ OK."
    ;;
  *)
    echo "No s'ha instal·lat. Es pot fer des d'Aplicacions (Actualitzar llista d'aplicacions) o amb:"
    echo "sudo -u $ODOO_USER $PYTHON $ODOO_BIN -c $ODOO_CONF -d $DB_NAME -i $MODULE_NAME --stop-after-init --no-http --max-cron-threads=0"
    exit 0
    ;;
esac

echo
read -r -p "Reiniciar $SERVICE ara (perquè tots els workers carreguin el mòdul)? [s/N] " RS || true
case "${RS,,}" in
  s|si|sí|y|yes) systemctl restart "$SERVICE"; echo "RESTART OK." ;;
  *) echo "Recorda: sudo systemctl restart $SERVICE" ;;
esac
echo "PROCÉS OK. Per desfer-ho abans d'instal·lar: rm -rf $TARGET"
