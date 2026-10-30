#!/usr/bin/env python3
"""
Generate FAKE demo data for the Veepee/Privalia dropshipping process.

Usage:
    python generate_demo_data.py OUT_DIR [small_orders=150] [large_units=10000]

All products, EANs, Veepee IDs, orders and destinations are invented.
Change SMALL_ORDERS / LARGE_UNITS (command line) to test any size.
"""
import os
import random
import sys
from collections import Counter, defaultdict
from math import ceil

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.indexed_list import IndexedList

OUT = sys.argv[1] if len(sys.argv) > 1 else "privalia_demo_kit"
SMALL_ORDERS = int(sys.argv[2]) if len(sys.argv) > 2 else 150
LARGE_UNITS = int(sys.argv[3]) if len(sys.argv) > 3 else 10000

GROUP_SIZE = 150                      # max orders per delivery group (warehouse preference, not a system limit)
BATCH_DATE = "07/10/2026"
BATCH_DATE_COMPACT = "071026"
DELIVERY_DATE = "2026-10-08 12:00:00"  # batch day + 1
CAMPAIGN = "DEMO01"
SMALL_BATCH_NO = 9900001
LARGE_BATCH_NO = 9900002
CUSTOMER = "DEMO MARKETPLACE SA"

random.seed(20261007)
os.makedirs(OUT, exist_ok=True)

HDR_FONT = Font(name="Arial", sz=10, bold=True)
HDR_FILL = PatternFill("solid", fgColor="D9E1F2")
NOTE_FONT = Font(name="Arial", sz=10, italic=True)


def new_wb():
    wb = Workbook()
    wb._fonts = IndexedList()
    wb._fonts.add(Font(name="Arial", sz=10))
    return wb


def fill_sheet(ws, header, rows, widths=None):
    ws.append(header)
    for c in ws[1]:
        c.font = HDR_FONT
        c.fill = HDR_FILL
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for i, h in enumerate(header, 1):
        w = (widths or {}).get(h, min(max(len(str(h)) + 2, 12), 42))
        ws.column_dimensions[get_column_letter(i)].width = w


def save(wb, name):
    path = os.path.join(OUT, name)
    wb.save(path)
    return path


# ------------------------------------------------------------------ catalogue
CATS = ["DRESS", "T-SHIRT", "JOGGER", "JACKET", "SKIRT", "LEGGINGS", "SWEATER", "SHIRT"]
DESCS = ["STAR", "FLORAL", "STRIPE", "DENIM", "SUNSET", "FOREST", "OCEAN", "CLOUD", "RETRO", "SPORT"]
COLORS = ["BLUE", "RED", "GREEN", "PINK", "BLACK", "WHITE", "YELLOW", "GREY", "NAVY", "BEIGE"]
SIZES = ["2A", "3A", "4A", "5A", "6A"]
N_STYLES = 600


def ean13(body12):
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


variants = []
idx = 0
for s in range(1, N_STYLES + 1):
    style = f"991{s:05d}"
    cat = CATS[s % len(CATS)]
    desc = random.choice(DESCS)
    color = random.choice(COLORS)
    base = round(random.uniform(9, 29), 2)
    for size in SIZES:
        idx += 1
        variants.append(dict(
            idx=idx, style=style, size=size, cat=cat, desc=desc, color=color, base=base,
            ean=ean13(f"84{idx:010d}"),
            vp=str(83800000 + idx),
            ext=f"__export__.product_product_{100000 + idx}_{random.getrandbits(32):08x}",
        ))
N = len(variants)

all_idx = list(range(N))
random.shuffle(all_idx)
BLANK = set(all_idx[: int(0.30 * N)])                 # ~30% have no Veepee ID in Odoo yet
MTO = all_idx[N // 2: N // 2 + 60]                    # "MTO + Buy" test variants (linked purchase)
STOCKOUT = all_idx[N // 2 + 60: N // 2 + 72]          # variants with zero stock
SPECIAL = set(MTO) | set(STOCKOUT)

pool_idx = [i for i in range(N) if i not in SPECIAL]
pool_w = [min(random.paretovariate(1.2), 20) for _ in pool_idx]
cum = []
t = 0.0
for w in pool_w:
    t += w
    cum.append(t)

# ------------------------------------------------------------------ carriers / mapping
CARRIERS = [
    ("ES#ASM", 20), ("FR#COLISSIMO", 20), ("IT#GLS", 17), ("ES#M_REL_ES", 5), ("FR#M_RELAY_FR", 5),
    ("IT#M_RELAY_IT", 6), ("BE#BPOST", 4), ("DE#DHL_DE", 4), ("NL#DHL_NL", 3), ("ES#DHL_ES", 3),
    ("BE#M_RELAY_BNL", 2), ("NL#M_RELAY_BNL", 1), ("LU#BPOST", 1), ("NL#POSTNL", 2),
    ("CH#POSTECH_EB", 1), ("AT#DHL_DE", 1), ("LU#M_RELAY_BNL", 1), ("ES#PAACK_ES", 1),
]
CARRIER_KEYS = [c[0] for c in CARRIERS]
CARRIER_W = [c[1] for c in CARRIERS]


def tarifa_for(cc):
    return {"ES": "Demo - ES", "IT": "Demo - IT"}.get(cc, "Demo - FR_BENELUX")


MAPPING = {}
for key in CARRIER_KEYS:
    cc, car = key.split("#")
    MAPPING[key] = (f"{cc} - {car}", f"Demo - {cc} - {car}", tarifa_for(cc))

CITIES = {
    "ES": [("08001", "Barcelona"), ("28001", "Madrid"), ("46001", "Valencia"), ("41001", "Sevilla"), ("17001", "Girona")],
    "FR": [("75001", "Paris"), ("69001", "Lyon"), ("13001", "Marseille"), ("31000", "Toulouse"), ("33000", "Bordeaux")],
    "IT": [("00100", "Roma"), ("20100", "Milano"), ("10100", "Torino"), ("06121", "Perugia")],
    "BE": [("1000", "Bruxelles"), ("2000", "Antwerpen")],
    "LU": [("1111", "Luxembourg")],
    "NL": [("1011", "Amsterdam"), ("3011", "Rotterdam")],
    "CH": [("8001", "Zurich")],
    "DE": [("10115", "Berlin"), ("80331", "Muenchen")],
    "AT": [("1010", "Wien")],
}

LINE_CHOICES = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15]
LINE_W = [18, 18, 15, 12, 9, 7, 8, 5, 5, 3]   # ~4.5 lines per order


def gen_orders(n_orders=None, target_lines=None, pe_base=0, ref_base=0):
    orders, total, i = [], 0, 0
    while True:
        if n_orders is not None and i >= n_orders:
            break
        if target_lines is not None and total >= target_lines:
            break
        i += 1
        k = random.choices(LINE_CHOICES, LINE_W)[0]
        if target_lines is not None:
            k = min(k, target_lines - total)
        picks = []
        while len(picks) < k:
            v = random.choices(pool_idx, cum_weights=cum)[0]
            if v not in picks:
                picks.append(v)
        key = random.choices(CARRIER_KEYS, CARRIER_W)[0]
        pc, city = random.choice(CITIES[key.split("#")[0]])
        orders.append(dict(pe=str(pe_base + i), ref=str(ref_base + i * 7), key=key, pc=pc, city=city, lines=picks))
        total += k
    return orders


def inject(order, vi):
    if vi not in order["lines"]:
        order["lines"][0] = vi


small = gen_orders(n_orders=SMALL_ORDERS, pe_base=990100000, ref_base=539000000)
large = gen_orders(target_lines=LARGE_UNITS, pe_base=990200000, ref_base=539500000)

# --- controlled test cases injected in the small batch (orders are 1-based positions)
if len(small) >= 45:
    for n, vi in zip(range(24, 29), MTO[:5]):       # C6: linked purchase, receipt not done
        inject(small[n - 1], vi)
    for n, vi in zip(range(29, 32), MTO[5:8]):      # C7: linked purchase, receipt done
        inject(small[n - 1], vi)
    for n, vi in zip(range(40, 46), STOCKOUT[:6]):  # stockout test
        inject(small[n - 1], vi)
# --- stockout variants sprinkled in the large batch
for o in random.sample(large, min(40, len(large))):
    inject(o, random.choice(STOCKOUT))


def units(orders):
    return sum(len(o["lines"]) for o in orders)


# ------------------------------------------------------------------ price list
prices = {}
for v in variants:
    b = v["base"]
    prices[v["ean"]] = (round(b * 0.50, 4), round(b * 0.45, 4), round(b * 0.55, 4))
PRICE_COL = {"Demo - ES": 0, "Demo - FR_BENELUX": 1, "Demo - IT": 2}

BATCH_HEADER = ["PE", "Style", "COLOR", "SIZE", "Product_Code", "EAN_Code", "QTY", "Leido", "SEQ", "Caja",
                "LI_Intitule", "LI_Adresse", "LI_Complement", "LI_CodePostal", "LI_Ville", "LI_CodeRegion",
                "LI_Pays", "LI_Telephone", "CT_Email", "DO_DateLivr", "DO_Date"]


def batch_rows(orders, batch_no):
    rows = []
    for o in orders:
        for vi in o["lines"]:
            v = variants[vi]
            rows.append([
                o["pe"], f"GIRL-{v['cat']} {v['desc']}-{v['color']}-{v['style']}-{v['size']}", v["color"],
                f"{v['style']}#{v['size']}", f"{v['vp']}_{v['style']}#{v['size']}", v["ean"], "1", "0", "", "",
                f"{CAMPAIGN}#{batch_no}#{o['pe']}#{o['ref']}", "", "", o["pc"], o["city"], "", o["key"],
                "", "", "", "",
            ])
    return rows


def write_batch(orders, batch_no, fname):
    wb = new_wb()
    ws = wb.active
    ws.title = str(batch_no)
    fill_sheet(ws, BATCH_HEADER, batch_rows(orders, batch_no), widths={"Style": 48, "Product_Code": 28, "LI_Intitule": 36})
    save(wb, fname)


IMPORT_HEADER = ["ORDER", "CUSTOMER", "PRICELIST", "PRODUCT", "QUANTITY", "UOM", "DESCRIPTION", "PRICE",
                 "SALESPERSON", "TAX", "DATE", "DISCOUNT", "SEASON", "BRAND", "ORDER TYPE"]


def write_import(orders, batch_no, fname):
    rows = []
    for o in orders:
        _, _, tarifa = MAPPING[o["key"]]
        for vi in o["lines"]:
            v = variants[vi]
            rows.append([f"DP-{o['pe']}", CUSTOMER, tarifa, v["ean"], 1, "Unidades", "",
                         prices[v["ean"]][PRICE_COL[tarifa]], "", "IVA 21% (Bienes)", BATCH_DATE, "",
                         "WEB", "WEB", "PED. INICIAL"])
    wb = new_wb()
    ws = wb.active
    ws.title = "Hoja1"          # import sheet MUST be the first sheet
    fill_sheet(ws, IMPORT_HEADER, rows, widths={"CUSTOMER": 26, "PRICELIST": 22, "PRODUCT": 16, "TAX": 18})
    ws2 = wb.create_sheet(str(batch_no))   # raw batch must be the second sheet
    fill_sheet(ws2, BATCH_HEADER, batch_rows(orders, batch_no), widths={"Style": 48, "Product_Code": 28, "LI_Intitule": 36})
    save(wb, fname)


# ------------------------------------------------------------------ 01 products to create
demand = Counter()
for o in small + large:
    for vi in o["lines"]:
        demand[vi] += 1

wb = new_wb()
ws = wb.active
ws.title = "Products"
rows = []
for i, v in enumerate(variants):
    route = "MTO + Buy" if i in MTO else "Stock"
    rows.append([v["ext"], v["style"], f"DEMO {v['cat']} {v['desc']} {v['color']} {v['style']} ({v['size']})",
                 v["ean"], "Storable Product", v["base"], round(v["base"] * 0.4, 2), route,
                 None if i in BLANK else v["vp"]])
fill_sheet(ws, ["External ID", "Internal Reference", "Product Name", "Barcode", "Product Type", "Sales Price",
                "Cost", "Route (info only)", "Dropshipping Veepee Product ID"], rows,
           widths={"External ID": 46, "Product Name": 50, "Dropshipping Veepee Product ID": 30})
ws = wb.create_sheet("Initial stock")
rows = []
for i, v in enumerate(variants):
    q = 0 if i in SPECIAL else demand[i] + random.randint(3, 8)
    rows.append([v["ean"], v["style"], "WH/Stock", q])
fill_sheet(ws, ["Barcode", "Internal Reference", "Location", "Quantity"], rows, widths={"Barcode": 18})
ws = wb.create_sheet("Test flags")
rows = [[variants[i]["ean"], "MTO_BUY_TEST", "Zero stock: stock arrives through a linked purchase order"] for i in MTO]
rows += [[variants[i]["ean"], "STOCKOUT_TEST", "Zero stock: use to test stockout handling"] for i in STOCKOUT]
fill_sheet(ws, ["Barcode", "Flag", "Meaning"], rows, widths={"Barcode": 18, "Meaning": 60})
save(wb, "01_products_to_create.xlsx")

# ------------------------------------------------------------------ 02 variants export (daily export)
wb = new_wb()
ws = wb.active
ws.title = "Sheet1"
rows = [[v["ext"], v["style"], v["ean"], None if i in BLANK else v["vp"]] for i, v in enumerate(variants)]
fill_sheet(ws, ["ID", "Código Art.", "Código de barras", "Dropshipping Veepee Product ID"], rows,
           widths={"ID": 46, "Código de barras": 18, "Dropshipping Veepee Product ID": 30})
save(wb, "02_variants_export.xlsx")

# ------------------------------------------------------------------ 03/04 batches
write_batch(small, SMALL_BATCH_NO, f"03_batch_{len(small)}orders_{SMALL_BATCH_NO}_07-10-2026.xlsx")
write_batch(large, LARGE_BATCH_NO, f"04_batch_{units(large)}units_{LARGE_BATCH_NO}_07-10-2026.xlsx")

# ------------------------------------------------------------------ 05 mapping carrier
wb = new_wb()
ws = wb.active
ws.title = "Hoja1"
rows = [[k, MAPPING[k][0], MAPPING[k][1], MAPPING[k][2]] for k in CARRIER_KEYS]
fill_sheet(ws, ["LI_Pays", "asd", "odoo_carrier", "tarifa"], rows,
           widths={"LI_Pays": 18, "asd": 18, "odoo_carrier": 28, "tarifa": 22})
save(wb, "05_MAPPING_CARRIER.xlsx")

# ------------------------------------------------------------------ 06 price list by country
wb = new_wb()
ws = wb.active
ws.title = "Prices"
rows = [[v["ean"], *prices[v["ean"]]] for v in variants]
fill_sheet(ws, ["Code barre", "Tarifa ES", "Tarifa FR / BENELUX", "Tarifa IT"], rows, widths={"Code barre": 18})
save(wb, "06_price_list_by_country.xlsx")

# ------------------------------------------------------------------ 07/08 import sale order
write_import(small, SMALL_BATCH_NO, f"07_import_sale_order_{len(small)}orders.xlsx")
write_import(large, LARGE_BATCH_NO, f"08_import_sale_order_{units(large)}units.xlsx")

# ------------------------------------------------------------------ 09 order update template
UPD_HEADER = ["ID", "Fecha de entrega", "Referencia del pedido", "Payment Mode", "Remarks", "Comercial",
              "Equipo de ventas", "Plazos de pago", "Método entrega"]


def upd_rows(orders, batch_no):
    return [[None, DELIVERY_DATE, f"DP-{o['pe']}", "CONFIRMING / SIN AVISO / SIN RECURSO",
             f"{CAMPAIGN}#{batch_no}#{o['pe']}#{o['ref']}", "Online", "Online", "A LA VISTA",
             MAPPING[o["key"]][1]] for o in orders]


wb = new_wb()
ws = wb.active
ws.title = f"Update_{len(small)}orders"
fill_sheet(ws, UPD_HEADER, upd_rows(small, SMALL_BATCH_NO),
           widths={"ID": 40, "Fecha de entrega": 22, "Referencia del pedido": 22, "Payment Mode": 38, "Remarks": 36, "Método entrega": 28})
ws = wb.create_sheet(f"Update_{units(large)}units")
fill_sheet(ws, UPD_HEADER, upd_rows(large, LARGE_BATCH_NO),
           widths={"ID": 40, "Fecha de entrega": 22, "Referencia del pedido": 22, "Payment Mode": 38, "Remarks": 36, "Método entrega": 28})
ws = wb.create_sheet("READ ME")
for line in [
    "HOW TO USE THIS TEMPLATE",
    "1. Import the sale orders (file 07 or 08), then export them from Odoo with the update template (ID, delivery date, order reference, payment mode, remarks, salesperson, sales team, payment terms, delivery method).",
    "2. Paste the exported 'ID' (external ID) next to each order, matching on 'Referencia del pedido' (DP-<order number>).",
    "3. Fill the other columns with the values in this file and import the sheet back into Odoo.",
    "4. Do NOT import 'Referencia del pedido': it is only the lookup key (map it to 'Do not import').",
    "Delivery date = batch day + 1. Remarks = campaign#batch#order#marketplace reference. Delivery method = carrier from file 05.",
]:
    ws.append([line])
ws["A1"].font = HDR_FONT
ws.column_dimensions["A"].width = 150
save(wb, "09_order_update_template.xlsx")

# ------------------------------------------------------------------ 10 groups plan (formulas)


def order_sheet(wb, title, orders):
    ws = wb.create_sheet(title)
    ws.append(["Order", "Carrier key", "Group prefix", "Seq in carrier", "Units", "Group name"])
    for c in ws[1]:
        c.font = HDR_FONT
        c.fill = HDR_FILL
    seq = defaultdict(int)
    for r, o in enumerate(orders, start=2):
        seq[o["key"]] += 1
        ws.append([f"DP-{o['pe']}", o["key"], f"B-DP_{o['key'].replace('#', '_')}_{BATCH_DATE_COMPACT}",
                   seq[o["key"]], len(o["lines"]),
                   f'=C{r}&"_"&TEXT(INT((D{r}-1)/Rules!$B$2)+1,"00")'])
    for col, w in zip("ABCDEF", [16, 18, 30, 14, 8, 36]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    return len(orders) + 1


def summary_sheet(wb, title, order_title, last_row):
    ws = wb.create_sheet(title)
    ws.append(["Carrier key", "Orders", "Units", "Delivery groups", "Avg units per order"])
    for c in ws[1]:
        c.font = HDR_FONT
        c.fill = HDR_FILL
    for r, key in enumerate(CARRIER_KEYS, start=2):
        ws.append([key,
                   f"=COUNTIF({order_title}!$B$2:$B${last_row},A{r})",
                   f"=SUMIF({order_title}!$B$2:$B${last_row},A{r},{order_title}!$E$2:$E${last_row})",
                   f"=ROUNDUP(B{r}/Rules!$B$2,0)",
                   f"=IF(B{r}=0,0,C{r}/B{r})"])
    tr = len(CARRIER_KEYS) + 2
    ws.append(["TOTAL", f"=SUM(B2:B{tr - 1})", f"=SUM(C2:C{tr - 1})", f"=SUM(D2:D{tr - 1})", f"=IF(B{tr}=0,0,C{tr}/B{tr})"])
    for c in ws[tr]:
        c.font = HDR_FONT
    for r in range(2, tr + 1):
        ws[f"E{r}"].number_format = "0.0"
    for col, w in zip("ABCDE", [20, 12, 12, 18, 20]):
        ws.column_dimensions[col].width = w


wb = new_wb()
ws = wb.active
ws.title = "Rules"
ws.append(["Parameter", "Value"])
for c in ws[1]:
    c.font = HDR_FONT
    c.fill = HDR_FILL
ws.append(["Max orders per delivery group (editable)", GROUP_SIZE])
ws.append(["Group naming", "B-DP_<country>_<carrier>_<ddmmyy>_<NN>"])
ws.append(["Batch date (ddmmyy)", BATCH_DATE_COMPACT])
ws.append(["Note", "150 orders is a warehouse preference (about 650-700 items), not a system limit. Change B2 to test other sizes."])
ws["B2"].font = Font(name="Arial", sz=10, color="0000FF")
ws.column_dimensions["A"].width = 44
ws.column_dimensions["B"].width = 70
lr_small = order_sheet(wb, "Orders_small", small)
lr_large = order_sheet(wb, "Orders_large", large)
summary_sheet(wb, "Summary_small", "Orders_small", lr_small)
summary_sheet(wb, "Summary_large", "Orders_large", lr_large)
save(wb, "10_groups_plan.xlsx")

# ------------------------------------------------------------------ 11 cancellation test
SCEN = [
    ("C1", "Cancel right after import (draft)", "Sale order imported, not confirmed",
     "Cancel the sale order.", "Order cancelled, nothing else created. Time taken."),
    ("C2", "Cancel confirmed order, nothing reserved", "Confirmed, delivery order created, not in a group",
     "Cancel the sale order.", "Delivery order cancelled automatically? Reservation released? Chatter shows who/when?"),
    ("C3", "Cancel after delivery is in a group", "Delivery order reserved and added to a delivery group",
     "Cancel the sale order.", "Is the order removed from the group? Are group totals updated? Any orphan lines?"),
    ("C4", "Cancel after the wave transfer was created", "Internal transfer to the sorter created, stock partly moved",
     "Cancel the sale order.", "What happens to the stock already moved to the sorter? Is the internal transfer quantity updated? Can the stock be put back without manual work?"),
    ("C5", "Cancel after shipment (delivery validated)", "Delivery done and sent to the carrier",
     "Cancel / return the sale order.", "Return flow, credit note, stock put back. Count the manual steps and the time."),
    ("C6", "Cancel with linked purchase (receipt not done)", "Sale order with MTO + Buy product; purchase order confirmed; receipt pending",
     "Cancel the sale order.", "Is the purchase order cancelled or reduced automatically? Is the link sale <-> purchase <-> receipt still visible?"),
    ("C7", "Cancel with linked purchase (receipt done)", "Purchase received into stock; sale order still open",
     "Cancel the sale order.", "Stock stays in warehouse and is reusable? Is the purchase kept as an orphan? Traceability of origin documents."),
    ("C8", "Bulk cancellation (marketplace cancels 20 orders)", "After the wave transfer was created, while users are working",
     "Cancel the 20 listed orders in one operation.", "Time for 20 orders, manual steps, documents left inconsistent, effect on picking in progress."),
]
wb = new_wb()
ws = wb.active
ws.title = "Scenarios"
fill_sheet(ws, ["ID", "Scenario", "Stage when the cancellation arrives", "Action", "What to check"],
           [list(s) for s in SCEN],
           widths={"ID": 6, "Scenario": 44, "Stage when the cancellation arrives": 56, "Action": 34, "What to check": 90})
ws = wb.create_sheet("Orders_to_cancel")
groups = [("C1", 1, 5), ("C2", 6, 10), ("C3", 11, 15), ("C4", 16, 20), ("C5", 21, 23),
          ("C6", 24, 28), ("C7", 29, 31), ("C8", 100, 119)]
rows = []
for sid, a, b in groups:
    for n in range(a, b + 1):
        if n - 1 < len(small):
            o = small[n - 1]
            rows.append([sid, f"DP-{o['pe']}", MAPPING[o["key"]][1], len(o["lines"]),
                         "Contains MTO + Buy product" if sid in ("C6", "C7") else ""])
fill_sheet(ws, ["Scenario", "Order", "Carrier", "Units", "Note"], rows, widths={"Order": 18, "Carrier": 28, "Note": 36})
ws = wb.create_sheet("Results_log")
ws.append(["HOW TO USE: run each scenario on the listed orders and log the result here. Blue cells = to fill in. Row 3 is an EXAMPLE, delete it."])
ws["A1"].font = NOTE_FONT
header = ["Scenario", "Order", "Start time", "End time", "Manual steps (clicks)", "Documents cancelled automatically",
          "Documents left open / inconsistent", "Traceability kept? (Y/N)", "Comments"]
ws.append(header)
for c in ws[2]:
    c.font = HDR_FONT
    c.fill = HDR_FILL
ws.append(["C2 (EXAMPLE)", "DP-990100006", "10:02:10", "10:02:45", 4, "Delivery order", "None", "Y", "Example row, replace with real results"])
for col, w in zip("ABCDEFGHI", [14, 18, 12, 12, 20, 34, 34, 22, 50]):
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"
save(wb, "11_cancellation_test.xlsx")

# ------------------------------------------------------------------ 12 expected ID import for the small batch
used = sorted({vi for o in small for vi in o["lines"] if vi in BLANK})
wb = new_wb()
ws = wb.active
ws.title = "Sheet1"
fill_sheet(ws, ["ID", "Dropshipping Veepee Product ID"], [[variants[i]["ext"], variants[i]["vp"]] for i in used],
           widths={"ID": 46, "Dropshipping Veepee Product ID": 30})
save(wb, "12_expected_ID_import_small_batch.xlsx")

print("orders small/large:", len(small), len(large), "| units small/large:", units(small), units(large))
print("variants:", N, "| blank VP ids:", len(BLANK), "| to update for small batch:", len(used))
