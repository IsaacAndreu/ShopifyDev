#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo bash stage_fedex_no_restart.sh ARCHIVE TARGET_MODULE_DIR
#
# Copies the validated module and creates a backup, but deliberately does not
# upgrade the database or restart Odoo. Use this only when you want to inspect
# the staged files before the real deployment.

ARCHIVE="${1:-}"
TARGET="${2:-/opt/tuctuc-erp/nath/custom_addons/delivery_fedex_rest2}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"

die() { echo "ERROR: $*" >&2; exit 1; }
[[ -n "$ARCHIVE" ]] || die "Falta ARCHIVE"
[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -d "$TARGET" ]] || die "No existeix el mòdul instal·lat: $TARGET"
case "$TARGET" in
  */custom_addons/delivery_fedex_rest2|*/custom_addons/*/delivery_fedex_rest2) ;;
  *) die "TARGET no sembla el mòdul esperat: $TARGET" ;;
esac

TMP_DIR="$(mktemp -d /tmp/fedex_stage.XXXXXX)"
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
grep -q "fedex_rest_shipment_state" "$MODULE_ROOT/models/delivery_carrier.py" || die "Falta el guard FedEx"
grep -q "FOR UPDATE" "$MODULE_ROOT/models/delivery_carrier.py" || die "Falta el bloqueig de picking"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${TARGET}.backup.${STAMP}"
TARGET_OWNER="$(stat -c '%u:%g' "$TARGET")"

sudo cp -a "$TARGET" "$BACKUP"
sudo cp -a "$MODULE_ROOT/." "$TARGET/"
sudo chown -R "$TARGET_OWNER" "$TARGET"

echo "STAGE OK: mòdul copiat sense reiniciar ni actualitzar la base de dades."
echo "Backup: $BACKUP"
echo "Target: $TARGET"
echo "Per activar-lo, usa deploy_fedex_restart.sh després de revisar-lo."
