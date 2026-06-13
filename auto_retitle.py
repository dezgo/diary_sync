"""Autonomous Phase-2 title pass — rename all remaining junk-titled PDF notes.

Processes every vault folder. For each junk note:
  1. Reads PDF text from the already-injected callout
  2. Extracts document date + entity via pattern matching
  3. Generates a YYYY-MM-DD Description title
  4. Renames the file and updates wikilinks (skips the vault scan for notes
     that are not referenced anywhere, which is almost all of them)

Writes a log to auto_retitle.log. Run with --dry to preview without writing.
"""
import re, sys, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, '.')
from pdf_note_tools import load_config, title_is_junk, _PDF_EMBED, _CALLOUT_BLOCK, _sanitise

# ── configuration ────────────────────────────────────────────────────────────

DRY = "--dry" in sys.argv
SNIPPET = 900   # chars of callout text to examine

config = load_config()
VAULT = Path(config["vault_path"])
LOG = Path(__file__).parent / "auto_retitle.log"

MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
          "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
MONTH_RE = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

# ── date extraction ───────────────────────────────────────────────────────────

_DATE_PATS = [
    # DD/MM/YYYY or DD-MM-YYYY
    re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2}|19\d{2})\b'),
    # YYYY-MM-DD
    re.compile(r'\b(20\d{2}|19\d{2})[/\-](\d{1,2})[/\-](\d{1,2})\b'),
    # DD Month YYYY
    re.compile(r'\b(\d{1,2})\s+(' + MONTH_RE + r')[a-z]*\s+(20\d{2}|19\d{2})\b', re.I),
    # Month DD, YYYY
    re.compile(r'\b(' + MONTH_RE + r')[a-z]*\s+(\d{1,2}),?\s+(20\d{2}|19\d{2})\b', re.I),
    # Month YYYY (no day — use 1st)
    re.compile(r'\b(' + MONTH_RE + r')[a-z]*\s+(20\d{2}|19\d{2})\b', re.I),
]

def _extract_date(text: str) -> str | None:
    """Return 'YYYY-MM-DD' for the first recognisable date in text, else None."""
    for pat in _DATE_PATS:
        m = pat.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if len(g) == 3:
                a, b, c = g
                au = a.lower()
                if au in MONTHS:          # Month DD YYYY
                    mo, day, yr = MONTHS[au], int(b), int(c)
                elif b.lower() in MONTHS: # DD Month YYYY
                    day, mo, yr = int(a), MONTHS[b.lower()], int(c)
                elif len(a) == 4:         # YYYY-MM-DD
                    yr, mo, day = int(a), int(b), int(c)
                else:                     # DD/MM/YYYY
                    day, mo, yr = int(a), int(b), int(c)
            else:                         # Month YYYY
                a, b = g
                mo, yr, day = MONTHS[a.lower()], int(b), 1
            if 1 <= mo <= 12 and 1 <= day <= 31 and 1900 <= yr <= 2030:
                return f"{yr:04d}-{mo:02d}-{day:02d}"
        except (ValueError, KeyError):
            continue
    return None

def _stem_date(stem: str) -> str:
    """Derive YYYY-MM-DD from a datestamp stem like 2012_04_06_11_54_00."""
    m = re.match(r'(\d{4})[_\-](\d{2})[_\-](\d{2})', stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r'(\d{2})(\d{2})(\d{4})', stem)   # DDMMYYYY
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return "1900-01-01"

# ── title generation ──────────────────────────────────────────────────────────

MEDICAL_KW = re.compile(
    r'\b(radiology|pathology|ultrasound|x-ray|xray|mri|ct scan|ct report|'
    r'patient|diagnosis|referral|prescription|hospital|clinic|outpatient|'
    r'canberra hospital|calvary|john james|dr\.|doctor|GP|physician|'
    r'specialist|surgery|anaes|endoscopy|colonoscopy|obstetric|paediatric|'
    r'physiotherapy|audiolog|optom|dental|allergy|asthma|epipen)\b', re.I)

GOVT_LAND_TAX = re.compile(r'\bland tax\b', re.I)
GOVT_RATES    = re.compile(r'\b(rates notice|rates assessment)\b', re.I)
GOVT_FINES    = re.compile(r'\binfringement notice\b', re.I)
GOVT_REGO     = re.compile(r'\b(vehicle registration|registration certificate)\b', re.I)
CERT_BIRTH    = re.compile(r'\b(birth certificate|extract of birth)\b', re.I)
CERT_OTHER    = re.compile(r'\bcertificate of\b', re.I)
INSURANCE     = re.compile(r'\b(certificate of insurance|insurance certificate|'
                            r'insurance policy|policy schedule|policy number)\b', re.I)
TENANCY       = re.compile(r'\b(tenancy agreement|residential tenancy|lease agreement)\b', re.I)
CONTRACT_SALE = re.compile(r'\bcontract for sale\b', re.I)
SETTLEMENT    = re.compile(r'\bsettlement statement\b', re.I)
CONVEYANCING  = re.compile(r'\b(conveyancing|transfer of land|mortgage)\b', re.I)
INVOICE       = re.compile(r'\b(tax invoice|invoice #|invoice no\.?|invoice number)\b', re.I)
RECEIPT       = re.compile(r'\b(receipt|purchase receipt|sales receipt)\b', re.I)
STATEMENT     = re.compile(r'\b(statement of account|account statement|bank statement|'
                            r'tran account|isaver|transaction account|savings account|'
                            r'zero tran|business zero|internet banking)\b', re.I)
PAYSLIP       = re.compile(r'\b(pay slip|payslip|pay advice|earnings statement|salary advice)\b', re.I)
SUPER         = re.compile(r'\b(superannuation|super statement|member statement|'
                            r'accumulation account|benefit statement)\b', re.I)
TAX_RETURN    = re.compile(r'\b(income tax return|tax return|ATO|notice of assessment)\b', re.I)
SCHOOL        = re.compile(r'\b(family statement|school fee|tuition fee|enrolment)\b', re.I)
CENTRELINK    = re.compile(r'\b(centrelink|centre link|family tax benefit|child care benefit)\b', re.I)
VINNIES       = re.compile(r'\b(vinnies|st vincent de paul|svdp)\b', re.I)
QUOTE         = re.compile(r'\b(quotation|quote no\.?|price estimate)\b', re.I)
WARRANTY      = re.compile(r'\b(warranty card|product warranty)\b', re.I)
WILL          = re.compile(r'\b(last will and testament|will and testament)\b', re.I)
BANK_NAME     = re.compile(
    r'\b(CommBank|Commonwealth Bank|CBA|NAB|ANZ|Westpac|'
    r'St\.?\s*George|Bankwest|Bendigo Bank|Macquarie Bank|HSBC|ING|Citibank)\b', re.I)

# Characters that reliably indicate garbled OCR
_GARBLE_CHARS = set('■•†←→↑↓◆◇▪▫□▶▷▸▹►▻▼▽▾▿◁◃◂◀◅«»¿¡¬¦°º×÷¥£€©®™^')
_TRAILING_NOISE = re.compile(
    r'\s+(SWITCHED|OICE|INVOICE|TAX INVOICE|Untitled|SWITCHED ON)\s*$', re.I)
_ENTITY_CLEAN = re.compile(
    r'\b(pty ltd|pty\. ltd\.|ltd|limited|pty|inc|corp|corporation|'
    r'pty limited|& co\.?|and co\.?)\b.*$', re.I)
_INVOICE_STRIP = re.compile(r'\s*(tax invoice|invoice|receipt)\s*$', re.I)

def _is_garbled(s: str) -> bool:
    """Return True if string looks like garbled OCR output."""
    if not s:
        return False
    if any(c in _GARBLE_CHARS for c in s):
        return True
    non_ascii = sum(1 for c in s if ord(c) > 127)
    if non_ascii / max(len(s), 1) > 0.12:
        return True
    symbols = sum(1 for c in s if not c.isalnum() and c not in " .,&-'/()+:@#%!=")
    if symbols / max(len(s), 1) > 0.25:
        return True
    # Mostly single-char words → garbled spacing
    words = s.split()
    if len(words) >= 3:
        short = sum(1 for w in words if len(w) <= 2)
        if short / len(words) > 0.55:
            return True
    return False

def _title_case_if_caps(s: str) -> str:
    """If s is ALL_CAPS (and meaningful length), return it title-cased."""
    alph = [c for c in s if c.isalpha()]
    if len(alph) < 4:
        return s
    upper = sum(1 for c in alph if c.isupper())
    if upper / len(alph) < 0.80:
        return s
    KEEP_CAPS = {'ACT', 'NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'NT',
                 'ATO', 'CBA', 'NAB', 'ANZ', 'ABN', 'ACN', 'ESTA', 'NRMA',
                 'AAMI', 'QBE', 'GIO', 'SVdP', 'ANU', 'ACU', 'TAFE',
                 'GST', 'BAS', 'PAYG', 'TFN'}
    words = s.split()
    return ' '.join(w if w.upper() in KEEP_CAPS else w.title() for w in words)

_LEAD_STRIP = re.compile(r'^[^a-zA-Z0-9(]+')

def _first_line(text: str, max_len: int = 50) -> str:
    """First non-empty, non-garbled, non-noise line truncated to max_len."""
    noise = re.compile(
        r'^[\W\d_]{0,3}$|^(page|www\.|http|abn|acn|untitled|\d[\d\s]{6,})\b', re.I)
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if noise.match(ln):
            continue
        # Lines that start with a math/operator char are usually garbled OCR
        if ln[0] in '+=%*|':
            continue
        if _is_garbled(ln):
            continue
        ln = _LEAD_STRIP.sub("", ln)        # strip leading junk prefix
        ln = _ENTITY_CLEAN.sub("", ln).strip().rstrip(",.")
        ln = _TRAILING_NOISE.sub("", ln).strip()
        if len(ln) < 3:
            continue
        return _title_case_if_caps(ln[:max_len])
    return ""

def _property_tag(text: str) -> str:
    """Extract a short property identifier if present."""
    for pat, tag in [
        (r'\b14 Broad Place\b',    "14 Broad Place Kambah"),
        (r'\b3 Lycett\b',          "3 Lycett St Weston"),
        (r'\b77 Boddington\b',     "77 Boddington Kambah"),
        (r'\b22 Meander\b',        "22 Meander St Warner"),
        (r'\bRed Hill\b',          "Red Hill"),
        (r'\bWeston\b',            "Weston"),
        (r'\bKambah\b',            "Kambah"),
        (r'\bBoddington\b',        "Boddington"),
        (r'\bBroad Place\b',       "Broad Place"),
    ]:
        if re.search(pat, text, re.I):
            return tag
    return ""

def _patient_tag(text: str) -> str:
    for pat, name in [
        (r'\b(Cassidy|Cass)\b',  "Cassidy"),
        (r'\b(Ashley|Ash)\b',    "Ashley"),
        (r'\b(Sabrina|Sabri)\b', "Sabrina"),
        (r'\bAdriana?\b',        "Adriana"),
        (r'\bDerek\b',           "Derek"),
    ]:
        if re.search(pat, text, re.I):
            return name
    return ""

def generate_title(stem: str, snippet: str) -> str:
    """Produce a human-readable title from document text + filename stem."""
    t = snippet
    date = _extract_date(t) or _stem_date(stem)
    fl   = _first_line(t)

    # --- medical (generic per Derek's rule) ---
    if MEDICAL_KW.search(t):
        who = _patient_tag(t)
        who_str = f" - {who}" if who else ""
        # identify sub-type
        if re.search(r'\bradiology\b|\bx-ray\b|\bxray\b|\bultrasound\b|\bmri\b|\bct scan\b', t, re.I):
            return f"{date} Radiology report{who_str}"
        if re.search(r'\bpathology\b', t, re.I):
            return f"{date} Pathology report{who_str}"
        if re.search(r'\bprescription\b', t, re.I):
            return f"{date} Prescription{who_str}"
        if re.search(r'\b(epipen|ascia|action plan)\b', t, re.I):
            return f"{date} ASCIA EpiPen action plan{who_str}"
        return f"{date} Medical document{who_str}"

    # --- government ---
    if GOVT_LAND_TAX.search(t):
        prop = _property_tag(t)
        # try to extract period
        pm = re.search(r'period\s+(\d{1,2}/\d{1,2}/\d{4})\s+to\s+(\d{1,2}/\d{1,2}/\d{4})', t, re.I)
        if pm:
            # use quarter from end date
            qd = _extract_date(pm.group(2)) or date
            return f"{qd} ACT land tax assessment{' - ' + prop if prop else ''}"
        return f"{date} ACT land tax assessment{' - ' + prop if prop else ''}"

    if GOVT_RATES.search(t):
        prop = _property_tag(t)
        return f"{date} Rates notice{' - ' + prop if prop else ''}"

    if GOVT_FINES.search(t):
        return f"{date} Infringement notice"

    if GOVT_REGO.search(t):
        return f"{date} Vehicle registration certificate"

    # --- certificates ---
    if CERT_BIRTH.search(t):
        who = _patient_tag(t)
        return f"{date} Birth certificate{' - ' + who if who else ''}"

    if INSURANCE.search(t):
        prop = _property_tag(t)
        # try to find insurer
        ins_m = re.search(r'\b(NRMA|AAMI|Suncorp|Allianz|QBE|CommInsure|MLC|'
                           r'AMP|ANZ|RACQ|GIO|Budget Direct|CGU|Zurich|Bupa|Medibank|HCF|HBF|NIB)\b', t)
        ins = ins_m.group(1) if ins_m else ""
        prop_str = " - " + prop if prop else ""
        ins_str = " " + ins if ins else ""
        return f"{date}{ins_str} insurance{' certificate' if 'certificate' in t.lower() else ' document'}{prop_str}"

    # --- property / legal ---
    if SETTLEMENT.search(t):
        prop = _property_tag(t)
        return f"{date} Settlement statement{' - ' + prop if prop else ''}"

    if CONTRACT_SALE.search(t):
        prop = _property_tag(t)
        return f"{date} Contract for sale{' - ' + prop if prop else ''}"

    if TENANCY.search(t):
        prop = _property_tag(t)
        return f"{date} Residential tenancy agreement{' - ' + prop if prop else ''}"

    if CONVEYANCING.search(t):
        prop = _property_tag(t)
        return f"{date} Conveyancing document{' - ' + prop if prop else ''}"

    # --- financial documents ---
    if SUPER.search(t):
        fund_m = re.search(r'\b(UniSuper|AustralianSuper|Sunsuper|REST|HESTA|Cbus|'
                            r'AMP|MLC|BT|Colonial First|Aware|LUCRF|QSuper|CARE)\b', t, re.I)
        fund = fund_m.group(1) if fund_m else ""
        return f"{date}{' ' + fund if fund else ''} superannuation statement"

    if TAX_RETURN.search(t):
        # extract year
        yr_m = re.search(r'\b(20\d{2})[/\-](20\d{2}|\d{2})\b|\b(income|tax)\s+year\s+(20\d{2})\b', t, re.I)
        return f"{date} ATO tax document"

    if PAYSLIP.search(t):
        return f"{date} Payslip"

    if CENTRELINK.search(t):
        return f"{date} Centrelink document"

    if STATEMENT.search(t):
        bank_m = re.search(r'\b(CommBank|Commonwealth Bank|CBA|NAB|ANZ|Westpac|'
                            r'St George|Bankwest|Bendigo|Macquarie|HSBC|ING|Citibank)\b', t, re.I)
        bank = bank_m.group(1) if bank_m else ""
        return f"{date}{' ' + bank if bank else ''} statement of account"

    # --- education ---
    if SCHOOL.search(t):
        school_m = re.search(r'\b(Orana|Steiner|St[\.\s]|Marist|Holy|Saint|'
                              r'University|College|Academy|Montessori)\b', t, re.I)
        school = school_m.group(0).strip() if school_m else ""
        who = _patient_tag(t)
        return f"{date}{' ' + school if school else ''} school fees{' - ' + who if who else ''}"

    # --- Vinnies / charity ---
    if VINNIES.search(t):
        return f"{date} SVdP document"

    # --- quotes ---
    if QUOTE.search(t):
        entity = fl or "trade"
        return f"{date} Quote - {entity[:40]}"

    # --- invoices ---
    if INVOICE.search(t):
        entity = fl or "supplier"
        # strip "invoice/receipt" suffix that OCR may have picked up in the entity line
        entity = _INVOICE_STRIP.sub("", entity).strip().rstrip(",. ")
        if not entity or len(entity) < 3:
            entity = "supplier"
        # capture invoice number — require at least one digit to avoid words like "INVOICE", "Phone"
        inv_m = re.search(
            r'(?:invoice|inv)[#\s\.nNo]*\b([A-Za-z0-9][A-Za-z0-9\-]*\d[A-Za-z0-9\-]*)\b', t, re.I)
        inv_n = f" {inv_m.group(1)}" if inv_m else ""
        return f"{date} {entity[:40]} invoice{inv_n}"

    # --- receipts ---
    if RECEIPT.search(t):
        entity = fl or "purchase"
        entity = _INVOICE_STRIP.sub("", entity).strip()
        return f"{date} {entity[:40] or 'purchase'} receipt"

    # --- warranty ---
    if WARRANTY.search(t):
        return f"{date} Warranty card"

    # --- will / legal ---
    if WILL.search(t):
        return f"{date} Last will and testament"

    # --- bank name without explicit statement keyword ---
    bm = BANK_NAME.search(t)
    if bm:
        return f"{date} {bm.group(1)} statement"

    # --- fallback: use first meaningful line ---
    _DANGLING = re.compile(r'\s+(of|the|a|an|in|to|at|by|for|and|or|with|from|de|van)\s*$', re.I)
    if fl and len(fl) > 6 and not re.match(r'^\d+$', fl) and not _DANGLING.search(fl):
        return f"{date} {fl[:60]}"

    # --- last resort ---
    return f"{date} Scanned document"


# ── bulk rename engine ────────────────────────────────────────────────────────

def build_ref_index(vault: Path) -> dict[str, list[Path]]:
    """Scan vault once to build stem -> [files that contain [[stem]]] map."""
    WIKILINK = re.compile(r'\[\[([^\]|#]+)')
    idx: dict[str, list[Path]] = defaultdict(list)
    for f in vault.rglob("*.md"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in WIKILINK.finditer(t):
            idx[m.group(1).strip()].append(f)
    return dict(idx)


def update_refs_for(old_stem: str, new_stem: str,
                    ref_idx: dict, vault: Path) -> int:
    files = ref_idx.get(old_stem, [])
    if not files:
        return 0
    link = re.compile(r'\[\[' + re.escape(old_stem) + r'(?=[\]|#])')
    changed = 0
    for f in files:
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        new = link.sub("[[" + new_stem, t)
        if new != t:
            if not DRY:
                f.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def _collision_safe(path: Path, stem: str) -> Path:
    """Append (2), (3)… until the candidate path is free."""
    candidate = path.with_name(stem + ".md")
    if not candidate.exists() or candidate == path:
        return candidate
    n = 2
    while True:
        candidate = path.with_name(f"{stem} ({n}).md")
        if not candidate.exists():
            return candidate
        n += 1


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Building wikilink reference index…", flush=True)
    ref_idx = build_ref_index(VAULT)
    print(f"  {len(ref_idx)} unique stems referenced across vault", flush=True)

    # Collect all junk notes
    all_notes = sorted([
        md for md in VAULT.rglob("*.md")
        if title_is_junk(md.stem)
        and _PDF_EMBED.search(md.read_text(encoding="utf-8", errors="ignore"))
    ], key=lambda p: (p.parent.name, p.stem))

    print(f"Found {len(all_notes)} junk-titled PDF notes to rename\n", flush=True)

    log_lines = []
    ok = skip = collision = 0

    for md in all_notes:
        text = md.read_text(encoding="utf-8", errors="ignore")
        # Extract snippet from callout
        cm = _CALLOUT_BLOCK.search(text)
        if cm:
            raw = cm.group(0)
            lines = [ln[2:] if ln.startswith("> ") else ln[1:] if ln.startswith(">") else ln
                     for ln in raw.splitlines()[1:]]
            snippet = "\n".join(lines).strip()[:SNIPPET]
        else:
            snippet = ""

        title = generate_title(md.stem, snippet)
        new_stem = _sanitise(title)
        if not new_stem:
            new_stem = f"{_stem_date(md.stem)} Scanned document"

        new_path = _collision_safe(md, new_stem)
        is_rename = new_path.name != md.name

        if not is_rename:
            skip += 1
            log_lines.append(f"SKIP  {md.relative_to(VAULT)}")
            continue

        if new_path.exists() and new_path != md:
            collision += 1
            log_lines.append(f"COLL  {md.relative_to(VAULT)}  ->  {new_path.name}")
            continue

        refs = update_refs_for(md.stem, new_stem, ref_idx, VAULT)
        if not DRY:
            md.rename(new_path)
        log_lines.append(f"OK    {md.stem!r:50s}  ->  {new_stem!r}" + (f"  ({refs} refs)" if refs else ""))
        ok += 1

        if ok % 100 == 0:
            print(f"  {ok} renamed…", flush=True)

    # Write log (always, so dry-run output can be inspected)
    log_out = (LOG.parent / "auto_retitle_dry.log") if DRY else LOG
    log_out.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n{'DRY RUN — ' if DRY else ''}Done:  {ok} renamed  |  {skip} skipped  |  {collision} collisions")
    print(f"Log: {LOG}")

if __name__ == "__main__":
    main()
