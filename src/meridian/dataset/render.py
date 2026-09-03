"""Render a document image from its label record."""
from __future__ import annotations

import os
import random
from typing import List

from PIL import Image, ImageDraw, ImageFont

from meridian.settings import FONT_DIR


CITIES = ["Ashford", "Bellhaven", "Corwin", "Draymoor", "Elsworth", "Fairmile"]


FONTS = {
    "mono":  os.path.join(FONT_DIR, "Courier New.ttf"),
    "monob": os.path.join(FONT_DIR, "Courier New Bold.ttf"),
    "sans":  os.path.join(FONT_DIR, "Arial.ttf"),
    "sansb": os.path.join(FONT_DIR, "Arial Bold.ttf"),
    "hand":  os.path.join(FONT_DIR, "Bradley Hand Bold.ttf"),
}


W, H = 850, 980


def _f(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[name], size)


def fmt_date(iso: str, style: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    if style == "iso":
        return iso
    if style == "us_slash":
        return "%02d/%02d/%04d" % (m, d, y)
    if style == "long":
        return "%s %d, %d" % (months[m - 1], d, y)
    return "%d %s %d" % (d, months[m - 1][:3], y)


def fmt_money(v: str, style: str) -> str:
    amount = float(v)
    if style == "dollar_comma":
        return "${:,.2f}".format(amount)
    if style == "dollar_plain":
        return "$%.2f" % amount
    return "%.2f USD" % amount


def _rows_for(rec: dict) -> List[tuple]:
    """Printable rows for a record, from the label."""
    f, r = rec["fields"], rec["render"]
    dfmt = r.get("date_format", "iso")
    absent = r.get("absent_field")

    blank_mode = r.get("absence_mode") == "blank_value"

    def row(key, label, value):
        if key == absent:
            # Printed label over an empty rule. The field is absent; the form
            # invites a guess.
            return (label, "__________________") if blank_mode else None
        if value is None:
            return None
        return (label, value)

    body = [
        row("claim_id", "Claim ID", f["claim_id"]),
        row("policy_number", "Policy No.", f["policy_number"]),
        row("claimant_name", "Claimant", f["claimant_name"]),
        row("date_of_service", "Date of Service",
            fmt_date(f["date_of_service"], dfmt) if f["date_of_service"] else None),
        row("provider_name", "Provider", f["provider_name"]),
    ]
    return [b for b in body if b]


OOD_BODIES = {
    "vehicle_registration": ("STATE OF ASHFORD - DEPT OF MOTOR VEHICLES",
                             "CERTIFICATE OF VEHICLE REGISTRATION",
                             [("Plate No.", "7KQD448"), ("VIN", "1HGCM82633A004352"),
                              ("Make / Model", "Volvo V70"), ("Year", "2019"),
                              ("Registered Owner", "B. Hollingsworth"),
                              ("Expires", "31 December 2027"), ("Class", "Passenger")]),
    "utility_bill": ("CORWIN MUNICIPAL POWER & WATER", "MONTHLY STATEMENT",
                     [("Account", "884-2201-9"), ("Service Address", "14 Tanner Row"),
                      ("Meter Reading", "48,221 kWh"), ("Billing Period", "Jul 1 - Jul 31"),
                      ("Usage Charge", "$142.18"), ("Amount Due", "$168.44"),
                      ("Due Date", "22 August 2026")]),
    "employee_timesheet": ("BELLHAVEN LOGISTICS LLC", "WEEKLY TIMESHEET",
                           [("Employee", "R. Castellanos"), ("Employee No.", "4417"),
                            ("Department", "Warehouse - Nights"),
                            ("Week Ending", "8 August 2026"), ("Regular Hours", "38.5"),
                            ("Overtime Hours", "6.0"), ("Supervisor", "T. Delacroix")]),
    "safety_datasheet": ("MATERIAL SAFETY DATA SHEET", "SECTION 4 - FIRST AID MEASURES",
                         [("Product", "Isopropyl Alcohol 70%"), ("CAS No.", "67-63-0"),
                          ("Signal Word", "DANGER"), ("Flash Point", "12 C"),
                          ("Storage Class", "3 - Flammable Liquids"),
                          ("Revision", "4 March 2026")]),
}


TITLES = {
    "claim_form": "CLAIM SUBMISSION FORM",
    "medical_invoice": "STATEMENT OF MEDICAL SERVICES",
    "adjuster_narrative": "ADJUSTER FIELD REPORT",
    "repair_estimate": "ESTIMATE OF REPAIR COST",
}


NARRATIVE = (
    "Attended site and inspected the reported loss. Damage is consistent with\n"
    "the account given by the claimant. Provider invoice reviewed against the\n"
    "schedule of allowances. Recommend settlement at the total shown below."
)


def render(rec: dict) -> Image.Image:
    r = rec["render"]
    rng = random.Random(r["seed"])
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    base = r.get("font", "mono")
    boldf = "monob" if base == "mono" else "sansb"
    y = 58

    if rec["stratum"] == "ood":
        header, title, rows = OOD_BODIES[rec["doc_type"]]
        d.text((60, y), header, font=_f(boldf, 20), fill=0); y += 40
        d.text((60, y), title, font=_f(base, 16), fill=0); y += 30
        d.line([(60, y), (W - 60, y)], fill=0, width=2); y += 34
        for label, value in rows:
            d.text((60, y), label, font=_f(base, 15), fill=60)
            d.text((300, y), value, font=_f(boldf, 15), fill=0)
            y += 34
        # No "this is not a claim" marker. A real OOD document does not
        # announce itself, and a footer would leak the label.
        d.text((60, H - 70), "Retain for your records.", font=_f(base, 11), fill=140)
        return img

    f = rec["fields"]
    # When provider_name is the absent field the letterhead must not leak it.
    letterhead = (f["provider_name"] or "MERIDIAN CLAIMS PROCESSING CENTER").upper()
    d.text((60, y), letterhead, font=_f(boldf, 19), fill=0); y += 30
    d.text((60, y), "%d %s Street, %s" % (rng.randint(10, 990),
           rng.choice(["Tanner", "Halloway", "Bridge", "Kestrel", "Mill"]),
           rng.choice(CITIES)), font=_f(base, 13), fill=90); y += 44

    d.text((60, y), TITLES[rec["doc_type"]], font=_f(boldf, 17), fill=0); y += 28
    d.line([(60, y), (W - 60, y)], fill=0, width=2); y += 36

    mfmt = r.get("money_format", "dollar_comma")
    for label, value in _rows_for(rec):
        d.text((60, y), label, font=_f(base, 15), fill=60)
        d.text((320, y), value, font=_f(boldf, 15), fill=0)
        y += 36

    y += 14
    if rec["doc_type"] == "adjuster_narrative":
        d.multiline_text((60, y), NARRATIVE, font=_f(base, 13), fill=25, spacing=8)
        y += 74

    # Itemisation comes from the label, so the arithmetic on the page is the
    # arithmetic under test.
    d.line([(60, y), (W - 60, y)], fill=140, width=1); y += 22
    for li in rec.get("reconciliation", {}).get("line_items", []):
        d.text((60, y), li["description"], font=_f(base, 13), fill=70)
        d.text((560, y), fmt_money(li["amount"], mfmt), font=_f(base, 13), fill=70)
        y += 26
    y += 12

    d.line([(60, y), (W - 60, y)], fill=0, width=1); y += 22

    # Ambiguous stratum: a second money figure of equal visual weight, above or
    # below the true total.
    def draw_total(y: int) -> int:
        """Draw the TOTAL DUE line at cursor y; return the new cursor."""
        if f["total_amount"] is None:
            if r.get("absence_mode") == "blank_value" and r.get("absent_field") == "total_amount":
                d.text((60, y), "TOTAL DUE:", font=_f(boldf, 16), fill=0)
                d.text((560, y), "__________________", font=_f(base, 15), fill=40)
                return y + 36
            return y
        money = fmt_money(f["total_amount"], mfmt)
        d.text((60, y), "TOTAL DUE:", font=_f(boldf, 16), fill=0)
        if r.get("handwritten_amount"):
            d.text((558, y - 4), money, font=_f("hand", 22), fill=15)
        else:
            d.text((560, y), money, font=_f(boldf, 16), fill=0)
        return y + 36

    def draw_distractor(y: int) -> int:
        """Draw the competing total, if any, at cursor y; return the new cursor."""
        if not r.get("distractor_total"):
            return y
        text = fmt_money(r["distractor_total"], mfmt)
        d.text((60, y), r["distractor_label"] + ":", font=_f(boldf, 16), fill=0)
        d.text((560, y), text, font=_f(boldf, 16), fill=0)
        if r.get("struck_through"):
            # Ruled through by hand; superseded.
            w = d.textlength(text, font=_f(boldf, 16))
            d.line([(556, y + 9), (566 + w, y + 7)], fill=20, width=2)
        return y + 36

    if r.get("distractor_position") == "below":
        y = draw_distractor(draw_total(y))
    else:
        y = draw_total(draw_distractor(y))
    y += 4

    d.text((60, H - 70), "Retain for your records.", font=_f(base, 11), fill=140)

    if r.get("form_rules"):
        # Pre-printed carbon-form rules that cross the typed values.
        for ry in range(190, min(y + 60, H - 90), 36):
            d.line([(50, ry), (W - 50, ry)], fill=95, width=1)

    if r.get("stamp"):
        img = _apply_stamp(img, rng)
    return img


def _apply_stamp(img: Image.Image, rng: random.Random) -> Image.Image:
    """An intake stamp rotated across the page over printed values.

    Composited with a darken blend so it obscures rather than replaces, like a
    rubber stamp over toner.
    """
    stamp = Image.new("L", (420, 90), 255)
    sd = ImageDraw.Draw(stamp)
    sd.text((14, 10), "RECEIVED", font=_f("sansb", 42), fill=70)
    sd.text((16, 58), "CLAIMS INTAKE", font=_f("sansb", 20), fill=70)
    sd.rectangle([(4, 4), (416, 86)], outline=70, width=3)
    stamp = stamp.rotate(rng.uniform(12, 28), resample=Image.BICUBIC,
                         expand=True, fillcolor=255)
    px, py = rng.randint(210, 330), rng.randint(300, 430)
    region = img.crop((px, py, px + stamp.width, py + stamp.height))
    from PIL import ImageChops
    img.paste(ImageChops.darker(region, stamp), (px, py))
    return img
