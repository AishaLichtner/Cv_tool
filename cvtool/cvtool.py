#!/usr/bin/env python3
"""
cvtool core – tailor a CV to job ads without inventing anything.

Principle: the language model may only select, reorder and rephrase. Every rephrased bullet is
checked deterministically against the fact base; on any violation the original text is used.
Start the browser UI with:  python app.py
"""
import base64, datetime, difflib, io, json, os, platform, re, shutil, stat, subprocess, sys
import tarfile, unicodedata, urllib.request, zipfile
from pathlib import Path

import jinja2

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CVTOOL_DATA") or HERE / "data")
FACTS = DATA / "facts.json"
SETTINGS_FILE = DATA / "settings.json"
OUT = DATA / "out"
BIN = HERE / "bin"
TEMPLATE = "template.tex.j2"
DEFAULT_MODEL = "claude-sonnet-5-5"
LENGTH_SLACK = 1.25
TECTONIC_VERSION = "0.15.0"

COMMON_TECH = """Spark Kafka Airflow dbt Snowflake Redshift AWS SageMaker Lambda Kubernetes K8s Terraform
PyTorch JAX LLM LLMs GenAI RAG LangChain Transformers Hugging Face NLP Computer Vision Scala Java Golang Rust
Julia C++ Tableau Power BI Looker Flink Hadoop Kubeflow Vertex AI Azure ML Fabric Synapse Data Factory
PostgreSQL MongoDB Elasticsearch Redis GraphQL FastAPI Flask Django React""".split()


# ================================================================ Settings & language

def load_settings() -> dict:
    s = {"lang": "de", "model": DEFAULT_MODEL, "max_pages": 2, "api_key": ""}
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return s

def save_settings(patch: dict) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    s = load_settings()
    for k in ("lang", "model", "max_pages", "api_key"):
        if k in patch and patch[k] is not None:
            s[k] = patch[k]
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s

def api_key() -> str:
    return load_settings().get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")

def lang() -> str:
    return "en" if load_settings().get("lang") == "en" else "de"

def lang_name() -> str:
    return "English" if lang() == "en" else "German"

MSG = {
    "kept_original": ("[{id}] Original behalten – {p}", "[{id}] Kept original – {p}"),
    "unsupported_term": ("nicht belegter Begriff '{t}'", "unsupported term '{t}'"),
    "new_numbers": ("neue Zahl(en) {n}", "new number(s) {n}"),
    "too_long": ("deutlich länger als das Original (Layout)", "much longer than the original (layout)"),
    "foreign_bullet": ("Unbekannter oder fremder Bullet '{id}' bei {c} verworfen",
                       "Unknown or foreign bullet '{id}' at {c} discarded"),
    "expertise_dropped": ("Expertise '{n}' verworfen (nicht in der Faktenbasis)",
                          "Expertise '{n}' discarded (not in the fact base)"),
    "no_valid_bullets": ("{c}: keine gültigen Bullets vom Modell – Original verwendet",
                         "{c}: no valid bullets from the model – original used"),
    "llm_check_kept": ("[{id}] LLM-Prüfung: Original behalten – {p}", "[{id}] LLM check: kept original – {p}"),
    "trim_bullet": ("Für {n} Seite(n) gekürzt: '{t}…' ({c})", "Trimmed to fit {n} page(s): '{t}…' ({c})"),
    "trim_skill": ("Für {n} Seite(n) gekürzt: Skill '{s}' ({g})", "Trimmed to fit {n} page(s): skill '{s}' ({g})"),
    "cannot_fit": ("Der CV passt nicht auf {n} Seite(n), auch nach dem Kürzen.",
                   "The CV does not fit on {n} page(s), even after trimming."),
    "fit_aborted": ("Kürzen nach mehreren Runden abgebrochen – bitte das PDF prüfen.",
                    "Stopped trimming after several rounds – please check the PDF."),
    "empty_jd": ("Die Stellenanzeige ist leer.", "The job ad is empty."),
    "empty_text": ("Bitte zuerst einen Text eingeben.", "Please enter some text first."),
    "no_api_key": ("Kein gültiger API-Key. Trag ihn unter „Einstellungen“ ein.",
                   "No valid API key. Enter it under “Settings”."),
    "no_credit": ("Dein API-Guthaben ist aufgebraucht. Lade es unter console.anthropic.com → Billing auf.",
                  "Your API credit is used up. Top it up at console.anthropic.com → Billing."),
    "no_structured": ("Keine strukturierte Antwort vom Modell erhalten. Bitte noch einmal versuchen.",
                      "Did not get a structured answer from the model. Please try again."),
    "invalid_json": ("Kein gültiges JSON: Zeile {l}, Spalte {c} – {m}", "Invalid JSON: line {l}, column {c} – {m}"),
    "missing_field": ("Pflichtfeld '{k}' fehlt.", "Required field '{k}' is missing."),
    "dup_ids": ("Doppelte Bullet-IDs: {ids}", "Duplicate bullet IDs: {ids}"),
    "empty_name": ("Jede Station und jedes Projekt braucht einen Namen.", "Every position and project needs a name."),
    "no_engine": ("Keine LaTeX-Engine gefunden. Unter „Einstellungen“ kannst du Tectonic mit einem Klick "
                  "herunterladen, oder du installierst MiKTeX/MacTeX/TeX Live.",
                  "No LaTeX engine found. Under “Settings” you can download Tectonic with one click, "
                  "or install MiKTeX/MacTeX/TeX Live."),
    "no_details": ("Keine Details verfügbar.", "No details available."),
    "hint": ("Tipp", "Tip"),
    "hint_cls": ("deedy-resume-openfont.cls fehlt im Programmordner.",
                 "deedy-resume-openfont.cls is missing from the program folder."),
    "hint_fonts": ("Schriften nicht gefunden. Der Ordner 'fonts' mit lato/ und raleway/ muss im Programmordner liegen.",
                   "Fonts not found. The 'fonts' folder with lato/ and raleway/ must be in the program folder."),
    "hint_pkg": ("Es fehlt ein LaTeX-Paket. In der MiKTeX Console „Fehlende Pakete installieren: Immer“ einstellen "
                 "(TeX Live: tlmgr install <paket>). Tectonic lädt Pakete automatisch.",
                 "A LaTeX package is missing. In the MiKTeX Console set “Install missing packages: Always” "
                 "(TeX Live: tlmgr install <package>). Tectonic downloads packages automatically."),
    "hint_network": ("Tectonic lädt beim ersten Lauf Pakete aus dem Internet. Prüfe die Internetverbindung.",
                     "Tectonic downloads packages from the internet on the first run. Check your connection."),
    # diagnose
    "d_engine": ("LaTeX-Engine", "LaTeX engine"),
    "d_engine_none": ("Keine gefunden. Tectonic herunterladen (Button oben) oder MiKTeX/MacTeX installieren.",
                      "None found. Download Tectonic (button above) or install MiKTeX/MacTeX."),
    "d_cls": ("Vorlage deedy-resume-openfont.cls", "Template deedy-resume-openfont.cls"),
    "d_fonts": ("Schriften (Lato, Raleway)", "Fonts (Lato, Raleway)"),
    "d_fonts_missing": ("Fehlende Dateien: {f}", "Missing files: {f}"),
    "d_key": ("API-Key", "API key"),
    "d_key_missing": ("Fehlt. Unter „Einstellungen“ eintragen.", "Missing. Enter it under “Settings”."),
    "d_profile": ("Persönliche Angaben", "Personal details"),
    "d_profile_missing": ("Name fehlt. Unter „Bearbeiten → Profil“ ausfüllen oder CV importieren.",
                          "Name missing. Fill in under “Edit → Profile” or import your CV."),
    "d_build": ("Standard-CV als PDF bauen", "Build default CV as PDF"),
    "d_pages": ("{n} Seite(n)", "{n} page(s)"),
    "d_trimmed": ("Zum Einpassen gekürzt:", "Trimmed to fit:"),
    "d_no_exp": ("Noch keine Erfahrung in der Faktenbasis – zuerst CV importieren.",
                 "No experience in the fact base yet – import your CV first."),
    # report
    "r_title": ("Bericht", "Report"), "r_cov": ("Keyword-Abdeckung", "Keyword coverage"),
    "r_kw": ("Keyword", "Keyword"), "r_imp": ("Wichtigkeit", "Importance"), "r_status": ("Status", "Status"),
    "r_legend": ("**abgedeckt** = stand schon im CV · **umformulierbar** = belegt in der Faktenbasis · "
                 "**LUECKE** = nicht belegt, wurde NICHT eingefügt",
                 "**abgedeckt** = already in the CV · **umformulierbar** = backed by the fact base · "
                 "**LUECKE** = not backed, NOT inserted"),
    "r_evidence": ("Mögliche Belege (bitte selbst prüfen)", "Possible evidence (check yourself)"),
    "r_changed": ("Umformulierte Bullets", "Rephrased bullets"), "r_before": ("vorher", "before"),
    "r_after": ("nachher", "after"), "r_none": ("(keine)", "(none)"),
    "r_log": ("Prüfprotokoll", "Check log"), "r_ok": ("alles ok", "all fine"),
}

def T(key: str, **kw) -> str:
    de, en = MSG[key]
    return (en if lang() == "en" else de).format(**kw)

class UserError(Exception):
    """Fehler mit einer Meldung, die direkt der Nutzerin gezeigt werden kann."""


# ================================================================ Text helpers

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9+#/]+", " ", s).strip()

def contains(haystack: str, term: str) -> bool:
    t = norm(term)
    return bool(t) and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", norm(haystack)) is not None

STOPWORDS = set("""a an and or of the with for in on to at by via from as into using use experience
knowledge strong solid proven hands understanding familiarity proficiency proficient skills skill
expertise background ability good deep excellent advanced working practical""".split())
SUFFIXES = ["izations", "isations", "ization", "isation", "izing", "ising", "ized", "ised", "izes", "ises",
            "ize", "ise", "ations", "ation", "ments", "ment", "ings", "ing", "ers", "er", "ies", "es", "s", "ed"]

def stem(w: str) -> str:
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w

def tokens(s: str) -> set:
    return {stem(w) for w in re.split(r"[\s/]+", norm(s)) if w and w not in STOPWORDS}

def matches(evidence: str, term: str) -> bool:
    """Exact hit, or all content words of the term (stemmed) occur in the SAME evidence text."""
    if contains(evidence, term):
        return True
    t = tokens(term)
    return bool(t) and t <= tokens(evidence)

def numbers(s: str) -> set:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))

TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}

def tex(s) -> str:
    return "".join(TEX_ESC.get(c, c) for c in str(s or ""))

def texurl(s) -> str:
    return re.sub(r"([%#\\{}])", r"\\\1", str(s or ""))

def slug(s: str, fallback="item") -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:24] or fallback


# ================================================================ Fact base

DEFAULT_GROUPS = ["Languages & Frameworks", "Platforms & Infrastructure", "Methods"]
LEGACY_PINNED = ["Python", "PySpark", "SQL"]

PROFILE_FIELDS = {"contacts": ["text", "url"],
                  "education": ["school", "degree", "location", "note_prefix", "note", "note_url"],
                  "certifications": ["name", "url"], "languages": ["name", "level"]}

def empty_profile() -> dict:
    return {"first_name": "", "last_name": "", "contacts": [], "education": [],
            "certifications": [], "languages": []}

def empty_facts() -> dict:
    return {"profile": empty_profile(), "expertise": [],
            "skill_groups": [{"name": g, "skills": []} for g in DEFAULT_GROUPS],
            "pinned_skills": [], "hidden_by_default": {"skills": [], "expertise": []},
            "experience": [], "projects": []}

def migrate(f: dict) -> dict:
    """Bringt aeltere facts.json auf den aktuellen Stand, ohne Inhalte zu verlieren."""
    for k in ("_hinweis",):
        f.pop(k, None)
    prof = f.get("profile") or {}
    if not (prof.get("first_name") or prof.get("last_name")):
        # kein Name hinterlegt: profile.json verwenden, falls vorhanden (auch nachtraeglich abgelegt)
        p = next((x for x in (DATA / "profile.json", HERE / "profile.json") if x.exists()), None)
        f["profile"] = json.loads(p.read_text(encoding="utf-8")) if p else (prof or empty_profile())
    for k, v in empty_profile().items():
        f["profile"].setdefault(k, v)
    for key, fields in PROFILE_FIELDS.items():
        f["profile"][key] = [{fld: (row.get(fld) or "") for fld in fields} for row in f["profile"][key] or []
                             if isinstance(row, dict)]
    f.setdefault("expertise", [])
    f.setdefault("skill_groups", [{"name": g, "skills": []} for g in DEFAULT_GROUPS])
    if "pinned_skills" not in f:   # fruehere Versionen hatten diese drei automatisch angeheftet
        names = {norm(s["name"]) for g in f["skill_groups"] for s in g["skills"]}
        f["pinned_skills"] = [p for p in LEGACY_PINNED if norm(p) in names]
    hb = f.get("hidden_by_default")
    if isinstance(hb, list):
        f["hidden_by_default"] = {"skills": hb, "expertise": []}
    f.setdefault("hidden_by_default", {"skills": [], "expertise": []})
    f["hidden_by_default"].pop("_hinweis", None)
    f["hidden_by_default"].setdefault("skills", [])
    f["hidden_by_default"].setdefault("expertise", [])
    f.setdefault("experience", [])
    f.setdefault("projects", [])
    for e in f["experience"]:
        for k in ("company", "title", "dates", "location"):
            e.setdefault(k, "")
        e.setdefault("bullets", [])
    for p in f["projects"]:
        p.setdefault("name", "")
        p.setdefault("dates", "")
        p.setdefault("bullets", [])
    return f

def load_facts() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    legacy = HERE / "facts.json"
    if not FACTS.exists() and legacy.exists():      # alte Ordnerstruktur: Datei in den Datenordner holen
        shutil.copy(legacy, FACTS)
    if not FACTS.exists():
        return empty_facts()
    raw = json.loads(FACTS.read_text(encoding="utf-8"))
    prof = raw.get("profile") or {}
    needs_save = (not (prof.get("first_name") or prof.get("last_name"))
                  and any(x.exists() for x in (DATA / "profile.json", HERE / "profile.json"))) \
                 or "pinned_skills" not in raw
    facts = migrate(raw)
    if needs_save:          # Migration einmalig festschreiben
        save_facts(facts)
    return facts

def save_facts(facts: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    if FACTS.exists():
        shutil.copy(FACTS, FACTS.with_suffix(".json.bak"))
    FACTS.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def all_bullets(facts):
    for e in facts["experience"]:
        for b in e["bullets"]:
            yield e, b
    for p in facts.get("projects", []):
        for b in p["bullets"]:
            yield p, b

def all_skills(facts):
    for g in facts["skill_groups"]:
        for s in g["skills"]:
            yield g, s

def evidence_text(b: dict) -> str:
    return " | ".join([b["text"], *b.get("skills", []), *b.get("synonyms", [])])

def container_name(c: dict) -> str:
    return c.get("company") or c.get("name") or ""


# ================================================================ Rendering

def jinja_env():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HERE),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        trim_blocks=True, lstrip_blocks=True, autoescape=False, undefined=jinja2.StrictUndefined)
    env.filters["tex"] = tex
    env.filters["texurl"] = texurl
    return env

def hidden(facts, kind):
    return {norm(h) for h in facts.get("hidden_by_default", {}).get(kind, [])}

def pinned(facts) -> list:
    return facts.get("pinned_skills", [])

def order_skills(names: list, pins: list, prio: dict = None) -> list:
    pin_idx = {norm(p): i for i, p in enumerate(pins)}
    prio = prio or {}
    return sorted(names, key=lambda n: (0, pin_idx[norm(n)]) if norm(n) in pin_idx else (1, prio.get(norm(n), 999)))

def base_view(facts: dict) -> dict:
    hid_e, hid_s = hidden(facts, "expertise"), hidden(facts, "skills")
    pins = pinned(facts)
    hid_s -= {norm(p) for p in pins}
    return {
        "profile": facts["profile"],
        "pinned": pins,
        "expertise": [x["name"] for x in facts["expertise"] if norm(x["name"]) not in hid_e],
        "skill_groups": [{"name": g["name"],
                          "skills": order_skills([s["name"] for s in g["skills"] if norm(s["name"]) not in hid_s], pins)}
                         for g in facts["skill_groups"]],
        "experience": [{**{k: e.get(k, "") for k in ("company", "title", "dates", "location")},
                        "bullets": [b["text"] for b in e["bullets"]]} for e in facts["experience"]],
        "projects": [{"name": p["name"], "dates": p.get("dates", ""),
                      "bullets": [b["text"] for b in p["bullets"]]} for p in facts.get("projects", [])],
    }

def render(view: dict) -> str:
    return jinja_env().get_template(TEMPLATE).render(**view)


# ================================================================ LaTeX engine

LAST_LATEX_ERROR = None

REQUIRED_FONTS = {"lato": ["Lato-Lig.ttf", "Lato-LigIta.ttf", "Lato-Reg.ttf", "Lato-RegIta.ttf",
                           "Lato-Hai.ttf", "Lato-Bol.ttf"],
                  "raleway": ["Raleway-ExtraLight.otf", "Raleway-Medium.otf"]}

def find_fonts_root():
    if (HERE / "fonts" / "lato" / "Lato-Lig.ttf").exists():
        return HERE / "fonts"
    for f in HERE.rglob("Lato-Lig.ttf"):
        if DATA not in f.parents and (f.parent.parent / "raleway").is_dir():
            return f.parent.parent
    return None

def missing_fonts():
    root = find_fonts_root()
    return [f"{d}/{n}" for d, names in REQUIRED_FONTS.items() for n in names
            if root is None or not (root / d / n).exists()]

def tectonic_path():
    exe = "tectonic.exe" if sys.platform.startswith("win") else "tectonic"
    local = BIN / exe
    return str(local) if local.exists() else shutil.which("tectonic")

def find_engine():
    """('xelatex', pfad) bevorzugt, sonst ('tectonic', pfad), sonst (None, None)."""
    xe = shutil.which("xelatex")
    if xe:
        return "xelatex", xe
    tc = tectonic_path()
    if tc:
        return "tectonic", tc
    return None, None

def tectonic_asset():
    m = platform.machine().lower()
    arm = m in ("arm64", "aarch64")
    if sys.platform.startswith("win"):
        return "x86_64-pc-windows-msvc.zip"
    if sys.platform == "darwin":
        return ("aarch64" if arm else "x86_64") + "-apple-darwin.tar.gz"
    return ("aarch64-unknown-linux-musl.tar.gz" if arm else "x86_64-unknown-linux-musl.tar.gz")

def download_tectonic() -> str:
    """Laedt die Tectonic-Engine (~20 MB) fuer dieses Betriebssystem in den Ordner bin/."""
    asset = tectonic_asset()
    url = (f"https://github.com/tectonic-typesetting/tectonic/releases/download/"
           f"tectonic%40{TECTONIC_VERSION}/tectonic-{TECTONIC_VERSION}-{asset}")
    with urllib.request.urlopen(url, timeout=120) as r:
        blob = r.read()
    BIN.mkdir(exist_ok=True)
    exe = "tectonic.exe" if asset.endswith(".zip") else "tectonic"
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.endswith("tectonic.exe"))
            (BIN / exe).write_bytes(z.read(name))
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
            member = next(m for m in t.getmembers() if m.name.endswith("tectonic"))
            (BIN / exe).write_bytes(t.extractfile(member).read())
        (BIN / exe).chmod((BIN / exe).stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(BIN / exe)

def _latex_error_excerpt(tex_path: Path, output: str) -> str:
    log = tex_path.with_suffix(".log")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
    excerpt = []
    for i, line in enumerate(lines):
        if line.startswith("!") or "Error" in line:
            excerpt += lines[i:i + 4]
            if len(excerpt) > 12:
                break
    text = "\n".join(excerpt) or "\n".join(output.strip().splitlines()[-15:]) or T("no_details")
    hints = []
    blob = text + output
    if re.search(r"deedy-resume-openfont\.cls", blob) and "not found" in blob:
        hints.append(T("hint_cls"))
    if re.search(r"font .* cannot be found|fontspec.*not found", blob, re.I):
        hints.append(T("hint_fonts"))
    if re.search(r"\.sty' not found|is not installed|package installation", blob, re.I):
        hints.append(T("hint_pkg"))
    if re.search(r"failed to (fetch|download)|network|resolve host|connection", blob, re.I):
        hints.append(T("hint_network"))
    return text + "".join(f"\n\n{T('hint')}: {h}" for h in hints)

def _run(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)

def compile_pdf(tex_path: Path):
    global LAST_LATEX_ERROR
    LAST_LATEX_ERROR = None
    shutil.copy(HERE / "deedy-resume-openfont.cls", tex_path.parent)
    root = find_fonts_root()
    if root:
        shutil.copytree(root, tex_path.parent / "fonts", dirs_exist_ok=True)
    pdf = tex_path.with_suffix(".pdf")
    if pdf.exists():
        pdf.unlink()
    kind, exe = find_engine()
    if not kind:
        LAST_LATEX_ERROR = T("no_engine")
        return None, None
    if kind == "xelatex":
        code, output = _run([exe, "-interaction=nonstopmode", "-halt-on-error", tex_path.name], tex_path.parent)
    else:
        code, output = _run([exe, "--keep-logs", tex_path.name], tex_path.parent)
    if not pdf.exists():
        LAST_LATEX_ERROR = _latex_error_excerpt(tex_path, output)
        print("  ! LaTeX:", LAST_LATEX_ERROR)
        return None, None
    try:
        from pypdf import PdfReader
        pages = len(PdfReader(pdf).pages)
    except Exception:
        pages = None
    return pdf, pages


# ================================================================ LLM

def _parse_json_text(text: str):
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            return json.loads(text[i:j + 1])
        raise

def llm_tool_call(system: str, user: str, tool_name: str, schema: dict, max_tokens=4096) -> dict:
    import anthropic
    key = api_key()
    if not key:
        raise UserError(T("no_api_key"))
    client = anthropic.Anthropic(api_key=key)
    sys_prompt = (system + f"\n\nAntworte AUSSCHLIESSLICH, indem du das Tool '{tool_name}' genau einmal "
                  "aufrufst. Kein Text davor oder danach.")
    messages = [{"role": "user", "content": user}]
    for _ in range(2):
        try:
            msg = client.messages.create(
                model=load_settings().get("model") or DEFAULT_MODEL, max_tokens=max_tokens, system=sys_prompt,
                tools=[{"name": tool_name, "description": "Return the result in structured form.",
                        "input_schema": schema}],
                tool_choice={"type": "auto"}, messages=messages)
        except anthropic.AuthenticationError:
            raise UserError(T("no_api_key"))
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower():
                raise UserError(T("no_credit"))
            raise
        for block in msg.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            data = _parse_json_text(text)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        messages = [{"role": "user", "content": user},
                    {"role": "assistant", "content": text or "(leer)"},
                    {"role": "user", "content": f"Bitte ruf jetzt das Tool '{tool_name}' auf."}]
    raise UserError(T("no_structured"))


KEYWORD_SCHEMA = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "object", "properties": {
        "term": {"type": "string"},
        "category": {"type": "string", "enum": ["tool", "method", "domain", "soft_skill", "other"]},
        "importance": {"type": "integer", "minimum": 1, "maximum": 3}},
        "required": ["term", "category", "importance"]}}},
    "required": ["keywords"]}

def extract_keywords(jd: str) -> list:
    return llm_tool_call(
        "Du extrahierst Anforderungen aus Stellenanzeigen fuer ATS-Optimierung. Nur Begriffe, die wirklich in "
        "der Anzeige stehen oder eindeutig gemeint sind. Kurze Begriffe (1-4 Woerter), keine Duplikate. "
        "Begriffe auf Englisch, ausser Eigennamen. importance: 3 = Muss, 2 = wichtig, 1 = nice to have.",
        jd, "keywords", KEYWORD_SCHEMA)["keywords"]


TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "expertise": {"type": "array", "items": {"type": "string"}},
        "skill_priority": {"type": "array", "items": {"type": "string"}},
        "include_hidden": {"type": "array", "items": {"type": "string"}},
        "experience": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "text": {"type": "string"}}, "required": ["id", "text"]}}},
            "required": ["id", "bullets"]}},
        "possible_evidence": {"type": "array", "items": {"type": "object", "properties": {
            "keyword": {"type": "string"}, "bullet_ids": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"}}, "required": ["keyword", "bullet_ids", "reason"]}}},
    "required": ["expertise", "skill_priority", "experience"]}

TAILOR_SYSTEM = """Du passt einen Lebenslauf an eine Stellenanzeige an. Die Fakten sind fest vorgegeben.

Erlaubt:
- Bullets pro Station/Projekt umsortieren (relevanteste zuerst) und weniger relevante weglassen (mind. 1 pro Eintrag).
- Bullets umformulieren, um Begriffe aus der Anzeige zu verwenden – aber NUR Begriffe aus "allowed_terms"
  des jeweiligen Bullets oder Woerter, die schon im Originaltext stehen.
- Expertise (max. 10, nur aus expertise_options) und Skills nach Relevanz sortieren.

Verboten:
- Neue Tools, Technologien, Methoden, Zahlen, Ergebnisse, Teamgroessen oder Verantwortlichkeiten.
- Verantwortung aufwerten (z. B. "contributed" -> "led"), wenn das Original es nicht sagt.
- Bullets zwischen Eintraegen verschieben.

Stil: in der Sprache der Originalbullets, knapp, aktive Verben, ohne Punkt am Ende. Ein Bullet darf
hoechstens wenig laenger werden. Passt ein Bullet schon, unveraendert lassen.

possible_evidence: nur fuer Keywords, die NICHT schon durch allowed_terms oder Originaltext gedeckt sind,
fuer die es aber plausible Belege gibt. Das Feld 'reason' schreibst du auf {LANG}."""

def tailor_llm(facts, keywords, max_bullets) -> dict:
    entries = facts["experience"] + facts.get("projects", [])
    payload = {
        "job_keywords": keywords, "max_total_bullets": max_bullets,
        "expertise_options": [x["name"] for x in facts["expertise"]],
        "skill_options": [s["name"] for _, s in all_skills(facts)],
        "hidden_by_default": [*facts["hidden_by_default"]["skills"], *facts["hidden_by_default"]["expertise"]],
        "experience": [{"id": e["id"], "name": container_name(e), "title": e.get("title", ""),
                        "bullets": [{"id": b["id"], "text": b["text"],
                                     "allowed_terms": b.get("skills", []) + b.get("synonyms", [])}
                                    for b in e["bullets"]]} for e in entries],
    }
    return llm_tool_call(TAILOR_SYSTEM.replace("{LANG}", lang_name()),
                         json.dumps(payload, ensure_ascii=False, indent=1), "tailored_cv", TAILOR_SCHEMA,
                         max_tokens=8000)


CHECK_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "supported": {"type": "boolean"},
                                     "problem": {"type": "string"}}, "required": ["id", "supported"]}}},
    "required": ["results"]}

def llm_check(pairs: list) -> dict:
    out = llm_tool_call(
        "Du pruefst Lebenslauf-Umformulierungen streng auf Ehrlichkeit. 'supported' ist nur true, wenn die neue "
        "Fassung nichts behauptet, was nicht aus Original + erlaubten Begriffen folgt (keine neuen Tools, Zahlen, "
        f"Ergebnisse, keine aufgewertete Verantwortung). 'problem' auf {lang_name()}.",
        json.dumps(pairs, ensure_ascii=False, indent=1), "check", CHECK_SCHEMA)
    return {r["id"]: r for r in out["results"]}


# ================================================================ Verification

def verify_bullet(orig: dict, new_text: str, watch_terms: list) -> list:
    problems, ev = [], evidence_text(orig)
    for term in watch_terms:
        if contains(new_text, term) and not matches(ev, term):
            problems.append(T("unsupported_term", t=term))
    extra = numbers(new_text) - numbers(orig["text"])
    if extra:
        problems.append(T("new_numbers", n=sorted(extra)))
    if len(new_text) > len(orig["text"]) * LENGTH_SLACK + 10:
        problems.append(T("too_long"))
    return problems

def build_tailored_view(facts, result, keywords, use_llm_check=False):
    log = []
    by_id = {b["id"]: b for _, b in all_bullets(facts)}
    watch = sorted({k["term"] for k in keywords} | set(COMMON_TECH)
                   | {s["name"] for _, s in all_skills(facts)}
                   | {a for _, s in all_skills(facts) for a in s.get("aliases", [])}, key=len, reverse=True)

    hid_e, hid_s = hidden(facts, "expertise"), hidden(facts, "skills")
    unhide = {norm(h) for h in result.get("include_hidden", [])}
    vis_e = lambda n: norm(n) not in hid_e or norm(n) in unhide
    vis_s = lambda n: norm(n) not in hid_s or norm(n) in unhide
    exp_names = {norm(x["name"]): x["name"] for x in facts["expertise"]}
    expertise = []
    for n in result.get("expertise", []):
        if norm(n) in exp_names:
            expertise.append(exp_names[norm(n)])
        else:
            log.append(T("expertise_dropped", n=n))
    view = base_view(facts)
    expertise = [n for n in dict.fromkeys(expertise) if vis_e(n)][:10] or view["expertise"]

    prio = {norm(n): i for i, n in enumerate(result.get("skill_priority", []))}
    pins = pinned(facts)
    pin_set = {norm(p) for p in pins}
    skill_groups = [{"name": g["name"], "skills": order_skills(
        [s["name"] for s in g["skills"] if vis_s(s["name"]) or norm(s["name"]) in pin_set], pins, prio)}
        for g in facts["skill_groups"]]

    proposed = {x["id"]: x["bullets"] for x in result.get("experience", [])}
    changed = []

    def tailor_container(e):
        own = {b["id"]: b for b in e["bullets"]}
        chosen = []
        for nb in proposed.get(e["id"], []):
            if nb["id"] not in own:
                log.append(T("foreign_bullet", id=nb["id"], c=container_name(e)))
                continue
            orig, text = own[nb["id"]], nb["text"].strip().rstrip(".")
            probs = verify_bullet(orig, text, watch)
            if probs:
                log.append(T("kept_original", id=orig["id"], p="; ".join(probs)))
                text = orig["text"]
            elif norm(text) != norm(orig["text"]):
                changed.append({"id": orig["id"], "original": orig["text"], "new": text,
                                "allowed_terms": orig.get("skills", []) + orig.get("synonyms", [])})
            chosen.append([orig["id"], text])
        if not chosen:
            if e["bullets"] and e["id"] in proposed:
                log.append(T("no_valid_bullets", c=container_name(e)))
            chosen = [[b["id"], b["text"]] for b in e["bullets"]]
        return chosen

    exp_sel = [(e, tailor_container(e)) for e in facts["experience"]]
    proj_sel = [(p, tailor_container(p)) for p in facts.get("projects", [])]

    if use_llm_check and changed:
        verdicts = llm_check(changed)
        for _, sel in exp_sel + proj_sel:
            for pair in sel:
                v = verdicts.get(pair[0])
                if v and not v["supported"]:
                    pair[1] = by_id[pair[0]]["text"]
                    log.append(T("llm_check_kept", id=pair[0], p=v.get("problem", "")))
                    changed[:] = [c for c in changed if c["id"] != pair[0]]

    view.update(
        expertise=expertise, skill_groups=skill_groups,
        experience=[{**{k: e.get(k, "") for k in ("company", "title", "dates", "location")},
                     "bullets": [t for _, t in sel]} for e, sel in exp_sel],
        projects=[{"name": p["name"], "dates": p.get("dates", ""), "bullets": [t for _, t in sel]}
                  for p, sel in proj_sel])
    return view, changed, log

def coverage(facts, keywords, base_tex):
    visible = [b["text"] for _, b in all_bullets(facts)]
    sources = ([evidence_text(b) for _, b in all_bullets(facts)]
               + [" | ".join([s["name"], *s.get("aliases", [])]) for _, s in all_skills(facts)]
               + [" | ".join([x["name"], *x.get("aliases", [])]) for x in facts["expertise"]])
    rows = []
    for k in sorted(keywords, key=lambda k: -k["importance"]):
        term = k["term"]
        if contains(base_tex, term) or any(matches(v, term) for v in visible):
            status = "abgedeckt"
        elif any(matches(s, term) for s in sources):
            status = "umformulierbar"
        else:
            status = "LUECKE"
        rows.append((k, status))
    return rows


# ================================================================ Fitting & runs

def fit_and_compile(view: dict, tex_path: Path, log: list, max_pages: int, max_rounds: int = 25):
    """Blocks are kept together by the template; this only trims if the page limit is exceeded."""
    pin_set = {norm(p) for p in view.get("pinned", [])}
    pdf = pages = None
    for rnd in range(max_rounds):
        tex_path.write_text(render(view), encoding="utf-8")
        pdf, pages = compile_pdf(tex_path)
        if not pdf or pages is None or pages <= max_pages:
            return pdf, pages
        entries = view["experience"] + view["projects"]
        longest = max(entries, key=lambda x: len(x["bullets"])) if entries else None
        changed = False
        groups = [g for g in view["skill_groups"]
                  if len(g["skills"]) > 2 and any(norm(s) not in pin_set for s in g["skills"])]
        if longest and len(longest["bullets"]) > 1 and (rnd % 2 == 0 or not groups):
            t = longest["bullets"].pop()
            log.append(T("trim_bullet", n=max_pages, t=t[:70], c=longest.get("company") or longest.get("name")))
            changed = True
        elif groups:
            g = max(groups, key=lambda g: len(g["skills"]))
            victim = [s for s in g["skills"] if norm(s) not in pin_set][-1]
            g["skills"].remove(victim)
            log.append(T("trim_skill", n=max_pages, s=victim, g=g["name"]))
            changed = True
        if not changed:
            log.append(T("cannot_fit", n=max_pages))
            return pdf, pages
    log.append(T("fit_aborted"))
    return pdf, pages

def run_render() -> dict:
    facts = load_facts()
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "cv_base.tex"
    log = []
    pdf, pages = fit_and_compile(base_view(facts), p, log, int(load_settings().get("max_pages", 2)))
    return {"tex": p, "pdf": pdf, "pages": pages, "log": log}

def run_tailor(jd: str, name: str = None, use_llm_check=False, max_pages: int = None) -> dict:
    if not jd.strip():
        raise UserError(T("empty_jd"))
    facts = load_facts()
    max_pages = max_pages or int(load_settings().get("max_pages", 2))
    name = re.sub(r"[^\w-]+", "_", name or "").strip("_") or datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "jobad.txt").write_text(jd, encoding="utf-8")

    keywords = extract_keywords(jd)
    base_tex = render(base_view(facts))
    max_bullets = sum(len(c["bullets"]) for c in facts["experience"] + facts["projects"])
    result = tailor_llm(facts, keywords, max_bullets)
    view, changed, log = build_tailored_view(facts, result, keywords, use_llm_check)

    tex_path = d / "cv.tex"
    pdf, pages = fit_and_compile(view, tex_path, log, max_pages)
    diff = "\n".join(difflib.unified_diff(base_tex.splitlines(), tex_path.read_text(encoding="utf-8").splitlines(),
                                          "cv_base.tex", "cv.tex", lineterm=""))
    (d / "diff.txt").write_text(diff, encoding="utf-8")

    cov = coverage(facts, keywords, base_tex)
    by_id = {b["id"]: b for _, b in all_bullets(facts)}
    covered = {norm(k["term"]) for k, s in cov if s != "LUECKE"}
    evidence = []
    for p in result.get("possible_evidence", []):
        ids = [i for i in p.get("bullet_ids", []) if i in by_id]
        if not ids or norm(p["keyword"]) in covered or any(matches(evidence_text(by_id[i]), p["keyword"]) for i in ids):
            continue
        evidence.append({"keyword": p["keyword"], "reason": p.get("reason", ""), "bullet_ids": ids,
                         "bullets": [{"id": i, "text": by_id[i]["text"]} for i in ids]})

    rep = [f"# {T('r_title')}: {name}\n", f"## {T('r_cov')}\n",
           f"| {T('r_kw')} | {T('r_imp')} | {T('r_status')} |", "|---|---|---|"]
    rep += [f"| {k['term']} | {'★' * k['importance']} | {s} |" for k, s in cov]
    rep += ["\n" + T("r_legend") + "\n"]
    if evidence:
        rep += [f"## {T('r_evidence')}\n"] + [f"- **{p['keyword']}** ← {', '.join(p['bullet_ids'])}: {p['reason']}"
                                              for p in evidence]
    rep += [f"\n## {T('r_changed')}\n"]
    rep += [f"- `{c['id']}`\n  - {T('r_before')}: {c['original']}\n  - {T('r_after')}: {c['new']}"
            for c in changed] or [T("r_none")]
    rep += [f"\n## {T('r_log')}\n"] + ([f"- {l}" for l in log] or [f"- {T('r_ok')}"])
    (d / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

    return {"name": name, "dir": d, "pdf": pdf, "pages": pages, "coverage": cov, "changed": changed,
            "log": log, "evidence": evidence, "gaps": [k["term"] for k, s in cov if s == "LUECKE" and k["importance"] == 3]}


# ================================================================ Editing

def find_skill(facts, name):
    for _, s in all_skills(facts):
        if norm(s["name"]) == norm(name) or any(norm(a) == norm(name) for a in s.get("aliases", [])):
            return s
    return None

def unique_id(base: str, taken: set) -> str:
    i, cid = 2, base
    while cid in taken:
        cid, i = f"{base}-{i}", i + 1
    taken.add(cid)
    return cid

def get_entries() -> dict:
    f = load_facts()
    return {"experience": f["experience"], "projects": f["projects"]}

def save_entries(data: dict) -> dict:
    """Speichert Stationen und Projekte aus dem Editor. Neue Eintraege/Bullets bekommen IDs."""
    facts = load_facts()
    stamp = datetime.date.today().isoformat()
    taken_c, taken_b = set(), set()
    out = {"experience": [], "projects": []}
    for kind in ("experience", "projects"):
        for c in data.get(kind, []):
            name = (c.get("company") if kind == "experience" else c.get("name")) or ""
            if not name.strip():
                raise UserError(T("empty_name"))
            cid = c.get("id") if c.get("id") and c["id"] not in taken_c else unique_id(slug(name, kind), taken_c)
            taken_c.add(cid)
            entry = {"id": cid, "dates": (c.get("dates") or "").strip(), "bullets": []}
            if kind == "experience":
                entry.update(company=name.strip(), title=(c.get("title") or "").strip(),
                             location=(c.get("location") or "").strip())
            else:
                entry["name"] = name.strip()
            for b in c.get("bullets", []):
                text = (b.get("text") or "").strip().rstrip(".")
                if not text:
                    continue
                bid = b.get("id") if b.get("id") and b["id"] not in taken_b else unique_id(f"{cid}-b", taken_b)
                taken_b.add(bid)
                entry["bullets"].append({"id": bid, "text": text,
                                         "skills": [s.strip() for s in b.get("skills", []) if s.strip()],
                                         "synonyms": [s.strip() for s in b.get("synonyms", []) if s.strip()],
                                         "source": b.get("source") or f"edit {stamp}"})
            out[kind].append(entry)
    facts["experience"], facts["projects"] = out["experience"], out["projects"]
    save_facts(facts)
    return {"ok": True}

def get_profile() -> dict:
    return load_facts()["profile"]

def save_profile(p: dict) -> dict:
    facts = load_facts()
    clean = empty_profile()
    clean["first_name"] = (p.get("first_name") or "").strip()
    clean["last_name"] = (p.get("last_name") or "").strip()
    keep = lambda rows, keys: [{k: (r.get(k) or "").strip() for k in keys} for r in rows or []
                               if any((r.get(k) or "").strip() for k in keys)]
    clean["contacts"] = keep(p.get("contacts"), ["text", "url"])
    clean["education"] = keep(p.get("education"), ["school", "degree", "location", "note_prefix", "note", "note_url"])
    clean["certifications"] = keep(p.get("certifications"), ["name", "url"])
    clean["languages"] = keep(p.get("languages"), ["name", "level"])
    facts["profile"] = clean
    save_facts(facts)
    return {"ok": True}

def get_skill_table() -> dict:
    facts = load_facts()
    pins, hid = {norm(p) for p in pinned(facts)}, hidden(facts, "skills")
    pin_order = {norm(p): i for i, p in enumerate(pinned(facts))}
    groups = [g["name"] for g in facts["skill_groups"]]
    rows = [{"name": s["name"], "aliases": s.get("aliases", []), "group": g["name"],
             "pinned": norm(s["name"]) in pins, "hidden": norm(s["name"]) in hid} for g, s in all_skills(facts)]
    rows.sort(key=lambda r: (groups.index(r["group"]), pin_order.get(norm(r["name"]), 999)))
    return {"groups": groups, "rows": rows}

def save_skill_table(rows: list, groups: list = None) -> dict:
    facts = load_facts()
    names = groups or [g["name"] for g in facts["skill_groups"]]
    grouped = {n: [] for n in names}
    pins, hidden_skills, moved = [], [], 0
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name or r.get("group") == "__delete__":
            continue
        if r.get("group") == "__expertise__":
            if not any(norm(name) == norm(x["name"]) for x in facts["expertise"]):
                facts["expertise"].append({"name": name, "aliases": r.get("aliases", [])})
            moved += 1
            continue
        grouped.setdefault(r["group"], []).append({"name": name, "aliases": r.get("aliases", [])})
        if r.get("pinned"):
            pins.append(name)
        elif r.get("hidden"):
            hidden_skills.append(name)
    facts["skill_groups"] = [{"name": n, "skills": s} for n, s in grouped.items()]
    facts["pinned_skills"] = pins
    facts["hidden_by_default"]["skills"] = hidden_skills
    save_facts(facts)
    return {"ok": True, "moved_to_expertise": moved}

def add_synonyms(additions: list) -> dict:
    facts = load_facts()
    by_id = {b["id"]: b for _, b in all_bullets(facts)}
    added = 0
    for a in additions:
        b, term = by_id.get(a.get("bullet_id")), (a.get("term") or "").strip()
        if b is not None and term and not any(norm(term) == norm(s) for s in b.setdefault("synonyms", [])):
            b["synonyms"].append(term)
            added += 1
    if added:
        save_facts(facts)
    return {"added": added}

def save_raw_facts(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise UserError(T("invalid_json", l=e.lineno, c=e.colno, m=e.msg))
    for key in ("expertise", "skill_groups", "experience"):
        if key not in data:
            raise UserError(T("missing_field", k=key))
    data = migrate(data)
    ids = [b["id"] for _, b in all_bullets(data)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise UserError(T("dup_ids", ids=", ".join(dupes)))
    save_facts(data)
    return {"ok": True}


# ================================================================ Add experience (free text)

ADD_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
        "new_bullets": {"type": "array", "items": {"type": "object", "properties": {
            "target": {"type": "string", "description": "ID eines bestehenden Eintrags oder 'new'"},
            "new_container": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["experience", "project"]},
                "company_or_name": {"type": "string"}, "title": {"type": "string"},
                "dates": {"type": "string"}, "location": {"type": "string"}}},
            "text": {"type": "string"}, "skills": {"type": "array", "items": {"type": "string"}},
            "synonyms": {"type": "array", "items": {"type": "string"}}},
            "required": ["target", "text", "skills", "synonyms"]}},
        "new_skills": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "group": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "group", "aliases"]}},
        "new_expertise": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions", "new_bullets", "new_skills", "new_expertise"]}

ADD_SYSTEM = """Du pflegst eine Faktenbasis fuer einen Lebenslauf. Die Person beschreibt frei, was sie gemacht
hat. Du wandelst das in strukturierte Eintraege um.

Regeln:
- Nur was im Text steht. Nichts ergaenzen, nicht aufwerten, keine Zahlen schaetzen.
- Fehlt Wichtiges (welche Station? Rolle? Zeitraum? Ergebnis?), stelle 1-3 kurze Rueckfragen in
  'questions' – auf {LANG}. Wurde eine Frage schon mit "weiss nicht"/leer beantwortet, ohne diese Info weiter.
- Bestehende Stationen/Projekte: target = deren id. Ein NEUES Projekt bzw. eine NEUE Station mit mehreren
  Bullets: alle Bullets mit target='new' und EXAKT demselben new_container (gleicher Name) – das ist EIN
  Eintrag mit mehreren Bullets, nicht mehrere Eintraege. Ein Projekt hat typischerweise 2-6 Bullets.
- new_skills NUR konkrete Werkzeuge: Sprachen, Bibliotheken, Plattformen, Dienste, Methoden. Taetigkeiten
  (z. B. "Data Migration", "ETL Pipelines") gehoeren an den Bullet und hoechstens in new_expertise.
- group: exakter Name einer bestehenden Skill-Gruppe.
- Skills, die es schon gibt (auch als Alias), NICHT als new_skills anlegen.
- Synonyme: nur Begriffe, die das Beschriebene wirklich bezeichnen.
- Bullets in der Sprache der bestehenden Bullets (meist Englisch), knapp, aktive Verben, kein Punkt am Ende."""

def summarize_facts(facts):
    return {"entries": [{"id": e["id"], "kind": "experience", "name": e["company"], "title": e.get("title", ""),
                         "dates": e.get("dates", "")} for e in facts["experience"]]
                       + [{"id": p["id"], "kind": "project", "name": p["name"], "dates": p.get("dates", "")}
                          for p in facts["projects"]],
            "skill_groups": {g["name"]: [s["name"] for s in g["skills"]] for g in facts["skill_groups"]},
            "expertise": [x["name"] for x in facts["expertise"]],
            "example_bullets": [b["text"] for _, b in list(all_bullets(facts))[:3]]}

def add_propose(text: str, qa: list = None, rounds: int = 0) -> dict:
    if not (text or "").strip():
        raise UserError(T("empty_text"))
    facts = load_facts()
    convo = text + "".join(f"\n\nFrage: {x['q']}\nAntwort: {x.get('a') or 'weiss nicht / nicht relevant'}"
                           for x in (qa or []))
    prop = llm_tool_call(ADD_SYSTEM.replace("{LANG}", lang_name()),
                         json.dumps({"faktenbasis": summarize_facts(facts), "beschreibung": convo},
                                    ensure_ascii=False, indent=1), "propose_facts", ADD_SCHEMA)
    if rounds >= 2:
        prop["questions"] = []
    prop["new_skills"] = [s for s in prop["new_skills"] if not find_skill(facts, s["name"])]
    known = {norm(n) for e in facts["expertise"] for n in (e["name"], *e.get("aliases", []))}
    prop["new_expertise"] = [x for x in dict.fromkeys(prop["new_expertise"]) if norm(x) not in known]
    prop["targets"] = {c["id"]: container_name(c) for c in facts["experience"] + facts["projects"]}
    prop["skill_groups"] = [g["name"] for g in facts["skill_groups"]]
    return prop

def add_apply(text: str, prop: dict) -> dict:
    """Uebernimmt Bullets. Neue Eintraege mit gleichem Namen werden zu EINEM Eintrag zusammengefasst,
    auch wenn es den Eintrag schon gibt."""
    facts = load_facts()
    stamp = datetime.date.today().isoformat()
    ids = {c["id"]: c for c in facts["experience"] + facts["projects"]}
    by_name = {("experience" if c in facts["experience"] else "project", norm(container_name(c))): c
               for c in facts["experience"] + facts["projects"]}
    taken_b = {b["id"] for _, b in all_bullets(facts)}
    added = 0
    for b in prop.get("new_bullets", []):
        if not (b.get("text") or "").strip():
            continue
        target = ids.get(b.get("target"))
        if target is None:
            c = b.get("new_container") or {}
            kind = "experience" if c.get("kind") == "experience" else "project"
            name = (c.get("company_or_name") or "").strip() or "New"
            target = by_name.get((kind, norm(name)))
            if target is None:
                cid = unique_id(slug(name), set(ids))
                if kind == "experience":
                    target = {"id": cid, "company": name, "title": c.get("title", ""),
                              "dates": c.get("dates", ""), "location": c.get("location", ""), "bullets": []}
                    facts["experience"].append(target)
                else:
                    target = {"id": cid, "name": name, "dates": c.get("dates", ""), "bullets": []}
                    facts["projects"].append(target)
                ids[cid], by_name[(kind, norm(name))] = target, target
        target["bullets"].append({"id": unique_id(f"{target['id']}-b", taken_b), "text": b["text"].strip().rstrip("."),
                                  "skills": b.get("skills", []), "synonyms": b.get("synonyms", []),
                                  "source": f"add {stamp}: {text.strip()[:500]}"})
        added += 1
    groups = {norm(g["name"]): g for g in facts["skill_groups"]}
    for s in prop.get("new_skills", []):
        if s.get("name") and not find_skill(facts, s["name"]):
            (groups.get(norm(s.get("group", ""))) or facts["skill_groups"][0])["skills"].append(
                {"name": s["name"], "aliases": s.get("aliases", [])})
    known = {norm(x["name"]) for x in facts["expertise"]}
    for x in prop.get("new_expertise", []):
        if x and norm(x) not in known:
            facts["expertise"].append({"name": x, "aliases": []})
            known.add(norm(x))
    save_facts(facts)
    return {"bullets": added}


# ================================================================ Import a whole CV

BULLET_ITEM = {"type": "object", "properties": {
    "text": {"type": "string"}, "skills": {"type": "array", "items": {"type": "string"}},
    "synonyms": {"type": "array", "items": {"type": "string"}}}, "required": ["text", "skills", "synonyms"]}

IMPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "profile": {"type": "object", "properties": {
            "first_name": {"type": "string"}, "last_name": {"type": "string"},
            "contacts": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "url": {"type": "string"}}, "required": ["text"]}},
            "education": {"type": "array", "items": {"type": "object", "properties": {
                "school": {"type": "string"}, "degree": {"type": "string"}, "location": {"type": "string"},
                "note_prefix": {"type": "string"}, "note": {"type": "string"}, "note_url": {"type": "string"}},
                "required": ["school"]}},
            "certifications": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "url": {"type": "string"}}, "required": ["name"]}},
            "languages": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "level": {"type": "string"}}, "required": ["name"]}}},
            "required": ["first_name", "last_name"]},
        "expertise": {"type": "array", "items": {"type": "string"}},
        "skill_groups": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "skills": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "skills"]}},
        "experience": {"type": "array", "items": {"type": "object", "properties": {
            "company": {"type": "string"}, "title": {"type": "string"}, "dates": {"type": "string"},
            "location": {"type": "string"}, "bullets": {"type": "array", "items": BULLET_ITEM}},
            "required": ["company", "bullets"]}},
        "projects": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "dates": {"type": "string"}, "bullets": {"type": "array", "items": BULLET_ITEM}},
            "required": ["name", "bullets"]}}},
    "required": ["profile", "expertise", "skill_groups", "experience", "projects"]}

IMPORT_SYSTEM = """Du uebertraegst einen bestehenden Lebenslauf (Text, LaTeX oder aus PDF kopiert) in eine
strukturierte Faktenbasis.

Regeln:
- Treu uebertragen: Bullets moeglichst im Originalwortlaut, nur LaTeX-Befehle entfernen. Nichts erfinden,
  nichts weglassen, was ein Fakt ist.
- Jede Station und jedes Projekt ist EIN Eintrag mit ALLEN seinen Bullets.
- Kontakte (E-Mail, Telefon, LinkedIn, GitHub, Website) als text + url (mailto: fuer E-Mail, sonst leer wenn
  keine URL bekannt).
- Skills in Gruppen: bevorzugt 'Languages & Frameworks', 'Platforms & Infrastructure', 'Methods'; nur echte
  Werkzeuge und Methoden. Taetigkeitsfelder in 'expertise'.
- Pro Bullet: skills = Werkzeuge/Methoden, die der Bullet nennt. synonyms = nur eindeutig gleichbedeutende
  Begriffe (z. B. PySpark -> 'Spark'); im Zweifel leer lassen."""

def extract_text_from_upload(filename: str, b64: str) -> str:
    raw = base64.b64decode(b64)
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    return raw.decode("utf-8", errors="replace")

def import_propose(text: str) -> dict:
    if not (text or "").strip():
        raise UserError(T("empty_text"))
    return llm_tool_call(IMPORT_SYSTEM, text[:60000], "cv_facts", IMPORT_SCHEMA, max_tokens=16000)

def import_apply(prop: dict, mode: str) -> dict:
    """mode: 'replace' (neue Faktenbasis), 'profile' (nur persoenliche Angaben), 'merge' (ergaenzen)."""
    facts = load_facts() if mode in ("profile", "merge") else empty_facts()
    stamp = datetime.date.today().isoformat()
    if mode in ("replace", "profile", "merge") and prop.get("profile"):
        if mode != "merge" or not facts["profile"].get("last_name"):
            facts["profile"] = migrate({"profile": prop["profile"], "expertise": [], "skill_groups": [],
                                        "experience": []})["profile"]
    if mode in ("replace", "merge"):
        known_e = {norm(x["name"]) for x in facts["expertise"]}
        for x in prop.get("expertise", []):
            if norm(x) not in known_e:
                facts["expertise"].append({"name": x, "aliases": []})
                known_e.add(norm(x))
        groups = {norm(g["name"]): g for g in facts["skill_groups"]}
        for g in prop.get("skill_groups", []):
            tg = groups.get(norm(g["name"]))
            if tg is None:
                tg = {"name": g["name"], "skills": []}
                facts["skill_groups"].append(tg)
                groups[norm(g["name"])] = tg
            for s in g.get("skills", []):
                if not find_skill(facts, s):
                    tg["skills"].append({"name": s, "aliases": []})
        facts["skill_groups"] = [g for g in facts["skill_groups"] if g["skills"]] or facts["skill_groups"]
        taken_c = {c["id"] for c in facts["experience"] + facts["projects"]}
        taken_b = {b["id"] for _, b in all_bullets(facts)}
        existing = {norm(container_name(c)) for c in facts["experience"] + facts["projects"]}
        for kind in ("experience", "projects"):
            for c in prop.get(kind, []):
                name = c.get("company") if kind == "experience" else c.get("name")
                if not name or (mode == "merge" and norm(name) in existing):
                    continue
                cid = unique_id(slug(name), taken_c)
                entry = {"id": cid, "dates": c.get("dates", ""), "bullets": []}
                if kind == "experience":
                    entry.update(company=name, title=c.get("title", ""), location=c.get("location", ""))
                else:
                    entry["name"] = name
                for b in c.get("bullets", []):
                    if b.get("text", "").strip():
                        entry["bullets"].append({"id": unique_id(f"{cid}-b", taken_b), "text": b["text"].strip().rstrip("."),
                                                 "skills": b.get("skills", []), "synonyms": b.get("synonyms", []),
                                                 "source": f"import {stamp}"})
                facts[kind].append(entry)
    save_facts(facts)
    return {"ok": True}


# ================================================================ Setup check & sharing

def template_is_current() -> bool:
    return "cvblock" in (HERE / TEMPLATE).read_text(encoding="utf-8")

def diagnose() -> list:
    checks = []
    add = lambda name, ok, detail="": checks.append({"name": name, "ok": bool(ok), "detail": detail})
    kind, exe = find_engine()
    add(T("d_engine"), kind, f"{kind}: {exe}" if kind else T("d_engine_none"))
    add(T("d_cls"), (HERE / "deedy-resume-openfont.cls").exists(), str(HERE / "deedy-resume-openfont.cls"))
    miss = missing_fonts()
    add(T("d_fonts"), not miss, str(find_fonts_root()) if not miss else T("d_fonts_missing", f=", ".join(miss)))
    add(T("d_key"), api_key(), "ok" if api_key() else T("d_key_missing"))
    facts = load_facts()
    add(T("d_profile"), facts["profile"].get("last_name"), "ok" if facts["profile"].get("last_name") else T("d_profile_missing"))
    if not facts["experience"] and not facts["projects"]:
        add(T("d_build"), False, T("d_no_exp"))
        return checks
    try:
        r = run_render()
        detail = (T("d_pages", n=r["pages"]) + (f"\n{T('d_trimmed')}\n" + "\n".join(r["log"]) if r["log"] else "")
                  if r["pdf"] else (LAST_LATEX_ERROR or ""))
        add(T("d_build"), r["pdf"], detail)
    except Exception as e:
        add(T("d_build"), False, str(e))
    return checks

SHARE_EXCLUDE = {"data", "bin", "__pycache__", ".venv", "venv", "out", ".git"}

def export_app_zip() -> bytes:
    """Programm ohne persoenliche Daten (data/), ohne heruntergeladene Engine und ohne venv."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(HERE.rglob("*")):
            rel = p.relative_to(HERE)
            if any(part in SHARE_EXCLUDE for part in rel.parts) or p.suffix in (".pyc", ".bak") or p.is_dir():
                continue
            if p.name in ("facts.json", "settings.json", "profile.json"):
                continue
            info = zipfile.ZipInfo(f"cvtool/{rel.as_posix()}", date_time=datetime.datetime.now().timetuple()[:6])
            mode = 0o755 if p.suffix in (".command", ".sh") else 0o644
            info.external_attr = (mode | 0o100000) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    return buf.getvalue()
