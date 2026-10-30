#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo bash deploy_fedex_restart.sh ARCHIVE TARGET_MODULE_DIR ODOO_SERVICE DB_NAME
#
# This script backs up the installed module, copies the validated module,
# restarts the service (restart only), upgrades the module database registry via
# --stop-after-init, and restarts the service again to load the upgraded fields.
# It never runs systemctl stop or systemctl start separately.

ARCHIVE="${1:-}"
TARGET="${2:-/opt/tuctuc-erp/nath/custom_addons/delivery_fedex_rest2}"
SERVICE="${3:-}"
DB_NAME="${4:-TUCTUC_PRODUCTION}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"
ODOO_BIN="${ODOO_BIN_PATH:-/opt/tuctuc-erp/odoo13/odoo-bin}"
ODOO_CONF="${ODOO_CONFIG:-/opt/tuctuc-erp/tuctuc-erp.conf}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Falta ARCHIVE"
[[ -n "$SERVICE" ]] || die "Falta ODOO_SERVICE"
[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -x "$ODOO_BIN" ]] || die "No puc executar Odoo: $ODOO_BIN"
[[ -r "$ODOO_CONF" ]] || die "No puc llegir la configuració: $ODOO_CONF"
[[ -d "$TARGET" ]] || die "No existeix el mòdul instal·lat: $TARGET"
case "$TARGET" in
  */custom_addons/delivery_fedex_rest2|*/custom_addons/*/delivery_fedex_rest2) ;;
  *) die "TARGET no sembla el mòdul esperat: $TARGET" ;;
esac

TMP_DIR="$(mktemp -d /tmp/fedex_deploy.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

case "$ARCHIVE" in
  *.tar.gz|*.tgz) tar -xzf "$ARCHIVE" -C "$TMP_DIR" ;;
  *.zip)
    command -v unzip >/dev/null 2>&1 || die "Falta unzip per llegir un .zip"
    unzip -q "$ARCHIVE" -d "$TMP_DIR"
    ;;
  *) die "Format no suportat: usa .tar.gz, .tgz o .zip" ;;
esac

MANIFEST="$(find "$TMP_DIR" -type f -path '*/delivery_fedex_rest2/__manifest__.py' -print -quit)"
[[ -n "$MANIFEST" ]] || die "L'arxiu no conté delivery_fedex_rest2/__manifest__.py"
MODULE_ROOT="$(dirname "$MANIFEST")"

mapfile -t PY_FILES < <(find "$MODULE_ROOT" -type f -name '*.py' -print)
"$PYTHON" -m py_compile "${PY_FILES[@]}"
mapfile -t XML_FILES < <(find "$MODULE_ROOT" -type f -name '*.xml' -print)
if (( ${#XML_FILES[@]} )); then
  "$PYTHON" -c 'import sys, xml.etree.ElementTree as ET; [ET.parse(p) for p in sys.argv[1:]]' "${XML_FILES[@]}"
fi
grep -q "fedex_rest_shipment_state" "$MODULE_ROOT/models/delivery_carrier.py" || die "L'arxiu no conté el guard FedEx"
grep -q "FOR UPDATE" "$MODULE_ROOT/models/delivery_carrier.py" || die "L'arxiu no conté el bloqueig de picking"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${TARGET}.backup.${STAMP}"
TARGET_OWNER="$(stat -c '%u:%g' "$TARGET")"

echo "=== DEPLOY FedEx amb restart ==="
echo "Backup: $BACKUP"
echo "Target: $TARGET"
echo "Servei: $SERVICE"
echo "Base de dades: $DB_NAME"

sudo cp -a "$TARGET" "$BACKUP"
sudo cp -a "$MODULE_ROOT/." "$TARGET/"
sudo chown -R "$TARGET_OWNER" "$TARGET"

echo "Reiniciant servei (systemctl restart; no stop/start separat)..."
sudo systemctl restart "$SERVICE"

echo "Actualitzant mòdul Odoo..."
sudo -u ubuntu "$PYTHON" "$ODOO_BIN" \
  -c "$ODOO_CONF" \
  -d "$DB_NAME" \
  -u delivery_fedex_rest2 \
  --no-http \
  --stop-after-init

echo "Reiniciant servei després de l'actualització..."
sudo systemctl restart "$SERVICE"

echo "DEPLOY OK. Backup conservat a: $BACKUP"
