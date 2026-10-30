# cvtool

**DE** · Passt deinen Lebenslauf an Stellenanzeigen an, ohne etwas zu erfinden.
**EN** · Tailors your CV to job ads without inventing anything.

---

## Deutsch

### Starten
1. **Python** installieren, falls noch nicht vorhanden: https://www.python.org/downloads/
   (Windows: bei der Installation „Add python.exe to PATH“ anhaken).
2. Ordner entpacken und **start.bat** (Windows) bzw. **start.command** (Mac) doppelklicken.
   Beim ersten Start wird alles Nötige automatisch installiert (1–2 Minuten).
   Mac: Falls „nicht verifizierter Entwickler“ erscheint → Rechtsklick auf start.command → Öffnen.
3. Der Browser öffnet sich. Unter **Einstellungen** deinen **API-Key** eintragen
   (console.anthropic.com → API Keys; Guthaben nötig, ein Durchlauf kostet nur Cent).
4. Unter **Hinzufügen → Ganzen CV importieren** deinen CV als PDF, LaTeX oder Text einlesen.
5. Unter **Bearbeiten** prüfen und korrigieren, dann unter **An Stelle anpassen** loslegen.

**LaTeX:** Ist kein LaTeX installiert, unter *Einstellungen* auf „LaTeX-Engine herunterladen (Tectonic)“
klicken. Wer MiKTeX, MacTeX oder TeX Live hat, braucht nichts weiter.

### Wie „nichts erfinden“ sichergestellt wird
Das Modell darf Bullets nur auswählen, sortieren und umformulieren. Jede Umformulierung wird gegen deine
Faktenbasis geprüft: Kommt ein Tool, eine Zahl oder ein Begriff vor, der für diesen Bullet nicht belegt ist,
wird der Originaltext verwendet. Belegt ist, was im Bullet steht oder als Skill/Synonym eingetragen ist.

### Deine Daten
Alles Persönliche liegt im Unterordner **data/** (Faktenbasis, API-Key, erzeugte CVs). Zum Teilen
*Einstellungen → Programm zum Teilen herunterladen* nutzen – das ZIP enthält **keine** persönlichen Daten.

---

## English

### Getting started
1. Install **Python** if needed: https://www.python.org/downloads/
   (Windows: tick “Add python.exe to PATH” during installation).
2. Unzip and double-click **start.bat** (Windows) or **start.command** (Mac).
   The first start installs everything automatically (1–2 minutes).
   Mac: if you see “unidentified developer” → right-click start.command → Open.
3. Your browser opens. Enter your **API key** under **Settings**
   (console.anthropic.com → API Keys; needs credit, one run costs cents).
4. Under **Add → Import whole CV** load your CV as PDF, LaTeX or text.
5. Review and fix under **Edit**, then use **Tailor to a job**.

**LaTeX:** if no LaTeX is installed, click “Download LaTeX engine (Tectonic)” under *Settings*.
With MiKTeX, MacTeX or TeX Live you need nothing else.

### How “nothing invented” is enforced
The model may only select, reorder and rephrase bullets. Every rephrasing is checked against your fact base:
if a tool, number or term appears that is not backed for that bullet, the original text is used. Backed means
it is in the bullet text or listed as a skill/synonym of that bullet.

### Your data
Everything personal lives in the **data/** subfolder (fact base, API key, generated CVs). To share, use
*Settings → Download program for sharing* – that ZIP contains **no** personal data.

---
Template: Deedy Resume (Apache 2.0). Fonts: Lato, Raleway (SIL Open Font License 1.1).
