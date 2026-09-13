# Änderungsprotokoll der Scoring-Schicht

Jede Änderung mit Begründung, erwartetem Nutzen, Risiko und Messergebnis.
Keine Änderung ohne nachvollziehbare Begründung; keine behauptete Verbesserung
ohne Messung.

**Messgrundlage für alle Zahlen unten:** `.cache/full_snaps.pkl` — echter
Produktions-Querschnitt vom 06.09.2026, 4.906 Titel mit echten Sektoren,
Branchen, Marktkapitalisierungen und Fundamentaldaten, bewertet mit der
Produktions-`ScoreEngine`.

---

## 2026-09-13 — Sofort-Defekte (D.1, D.2, D.4)

### D.1 — Nicht-positive Bewertungsmultiplikatoren

**OLD**
`ValuationComputor` bildete für `pe`, `ev_ebitda`, `p_fcf`, `p_b` das invertierte
Peer-Perzentil („klein ist besser") ohne Vorzeichenprüfung.

**NEW**
Nicht-positive Multiplikatoren gelten als *nicht definiert* und werden wie
fehlend behandelt — sowohl beim eigenen Wert als auch in der Peer-Verteilung.
Der Ausschluss wird über einen neutralen Driver (`multiple_undefined`) sichtbar
gemacht. Gibt es keinen einzigen positiven Multiplikator, liefert der Score
`missing` statt einer Zahl.

**WHY**
Ein negatives KGV/EV-EBITDA/KBV bedeutet nicht „billig", sondern dass die
Kennzahl als Bewertungsmaßstab nicht definiert ist (Verlust, negatives EBITDA,
negatives Eigenkapital). Die Invertierung drehte solche Werte an die *Spitze*
der Günstigkeits-Rangliste. Gemessen vor dem Fix:

| Kennzahl | negativ | Anteil | mittl. invertiertes Perzentil |
|---|---|---|---|
| ev_ebitda | 92 von 633 | 14,5 % | **0,70** (positiv: 0,46) |
| p_b | 66 von 712 | 9,3 % | **0,77** |

Konkret: `AHG` mit EV/EBITDA −447,5 → Perzentil 0,95 („billigst der Branche");
`MCK` mit P/B −24,8 (negatives Eigenkapital nach Rückkäufen) → 0,92.

**EXPECTED BENEFIT**
Verlustunternehmen und Gesellschaften mit negativem Buchwert erhalten keinen
systematischen Bewertungsbonus mehr.

**BACKTEST / MESSERGEBNIS**
718 Titel mit Fundamentaldaten:
- 125 von 696 (**18,0 %**) ändern ihren Valuation-Score um ≥ 0,5 Punkte
- 21 Titel verlieren die Bewertung vollständig (nur unbrauchbare Multiplikatoren)
- Streuung steigt von σ 1,52 auf **1,68** → der Score differenziert stärker
- Mittelwert praktisch unverändert (5,05 → 5,12), wie bei einem rangbasierten
  Maß zu erwarten
- Größte Korrekturen: `ADSE` 6,50 → 1,29 · `ADUR` 5,09 → 1,17 · `ABVX` 5,20 → 1,91

**RISK**
Titel mit ausschließlich negativen Multiplikatoren haben jetzt gar keinen
Valuation-Score mehr; das WLAFAR renormiert auf `fund_quality` + `growth`.
Das ist gewollt („ehrliches Unbekannt"), reduziert aber die Faktorabdeckung
dieser Titel. Bewusst **nicht** als „teuer" (Perzentil 0) gewertet — das wäre
eine zusätzliche Behauptung; die fehlende Profitabilität ist über
`fund_quality`/`growth` bereits erfasst.

**Nicht umgesetzt und warum:** Winsorizing der Multiplikatoren. Die Bewertung
läuft über Ränge, nicht über Niveaus — ein KGV von 4.000 belegt denselben
letzten Rang wie eines von 400. Durch Test abgesichert.

---

### D.2 — `structure_counts` maß keine Chartstruktur

**OLD**
```python
for i in range(1, len(seg)):           # benachbarte KERZEN
    if cur.h > prev.h: hh += 1
    else:              lh += 1
```
→ `hh + lh == n-1` per Konstruktion; Lookback 20 Bars.

**NEW**
HH/HL/LH/LL aus **Swing-Punkten** (Fraktale, `screener.zones.swing_points`,
window=2), Lookback 60 Bars. Unmittelbar aufeinanderfolgende *gleiche*
Swing-Preise werden zusammengefasst (`_collapse_plateaus`); gleiche Werte
zählen weder als höheres noch als tieferes Hoch.

**WHY**
Der aus diesen Zählern in `setup` gebildete „bullische Strukturanteil" war
faktisch ein Zähler für Aufwärtstage — also ein weiterer kurzfristiger
Momentum-Proxy neben RSI, MACD und Stochastik im *selben* Score. 20 Bars
enthalten zudem oft nur zwei bis drei Swings; ein Verhältnis daraus ist Rauschen.

Der Plateau-Fix entstand aus einem fehlgeschlagenen Test: `swing_points`
vergleicht mit `>=`, wodurch in einer Reihe mit wiederholt identischen Hochs
(bei illiquiden Titeln häufig) *jede* Kerze als Swing zählt. Da gleiche Werte
als „tieferes Hoch" gewertet wurden, sah eine flache Reihe stark bärisch aus.

**BACKTEST / MESSERGEBNIS** (4.769 Titel)

Auf **Faktor-Ebene** — deutliche Verbesserung:

| Rang-Korrelation des bullischen Strukturanteils | alt | neu |
|---|---|---|
| ret_1m | +0,56 | **+0,35** |
| RSI | +0,51 | **+0,33** |
| ret_3m | +0,45 | +0,58 |
| Streuung σ | 0,127 | **0,181** |

Auf **Composite-Ebene** — kaum Wirkung (1.468 Titel):

| | alt | neu |
|---|---|---|
| setup-Score σ | 0,862 | 0,821 |
| setup ↔ RSI | −0,38 | −0,36 |
| Rang-Korrelation alt ↔ neu | | **+0,95** |

**Ehrliche Einordnung:** Die Korrektur beseitigt eine falsche Bezeichnung und
verbessert den Faktor selbst messbar (Redundanz zur RSI 0,51 → 0,33), ändert
den `setup`-Score aber nur marginal, weil Struktur dort nur 10 % Gewicht trägt.
Das eigentliche Problem ist nicht dieser Teilfaktor, sondern `setup` als Ganzes
(σ ≈ 0,8 bei 12 % Nominalgewicht, Korrelation **−0,19 zum eigenen Composite**
WLATAR). Das gehört in die Ebenen-Trennung (P2), nicht in einen Teilfaktor-Fix.

**RISK**
Die Zeitskala des Faktors verschiebt sich von kurz- auf mittelfristig; die
Korrelation zu `ret_3m` steigt dadurch (+0,45 → +0,58). Da `ret_3m` die
Hauptkomponente von `rel_strength` ist, wandert eine kleine Redundanz vom
Setup- in den Trendbereich. Gewichtsanteil: 10 % von `setup` × 12 % im
WLATAR ≈ **1,2 %** — vernachlässigbar.

---

### D.4 — Zwei unterschiedliche Liquiditätsbegriffe

**OLD**
```python
avg_vol = info["averageVolume"]                     # Yahoo-Durchschnitt
avg_dollar_volume = avg_vol * price                 # x HEUTIGER Kurs
```
`screener/breakout_signal.py` nutzte dagegen bereits
`statistics.median(c.c * c.v)` über 60 Bars.

**NEW**
Neue Funktion `indicators.median_dollar_volume(candles, period=60)` — identische
Definition wie in `breakout_signal.py`. Verwendet in Yahoo- und FMP-Provider;
der alte Wert bleibt nur als Rückfallebene, wenn keine Kerzen vorliegen.

**WHY**
Der Tagesumsatz ist stark rechtsschief. Ein einzelner Nachrichtentag hebt den
arithmetischen Schnitt eines sonst illiquiden Titels über die Schwelle — genau
die Titel also, die der Filter (`< 2 Mio $` → Status `Vermeiden`) aussortieren
soll. Zusätzlich mischte die alte Formel zwei Zeitbezüge (3-Monats-
Durchschnittsvolumen × heutiger Kurs).

**BACKTEST / MESSERGEBNIS** (4.828 Titel)

| | alt | neu |
|---|---|---|
| als liquide eingestuft | 2.714 | 2.502 |
| Wechsel liquide → illiquide | | **247** |
| Wechsel illiquide → liquide | | 35 |
| Median Verhältnis neu/alt | | 0,89 |

Größte Korrekturen — vorher als handelbar geführt:

| Titel | alt | neu | Faktor |
|---|---|---|---|
| YJ | 15,8 Mio $ | 0,01 Mio $ | 2.567× |
| XHG | 14,8 Mio $ | 0,01 Mio $ | 2.393× |
| SWVL | 21,4 Mio $ | 0,02 Mio $ | 1.389× |
| XPON | 46,0 Mio $ | 0,09 Mio $ | 537× |

**RISK**
`Vermeiden` ist ein *hartes* Ereignis im `TransitionValidator` (ohne Hysterese).
Die 247 betroffenen Titel wechseln daher beim nächsten Lauf sofort in diesen
Status. Das ist beabsichtigt — eine Disqualifikation soll nicht zwei Läufe
warten. Da Snapshots über den GitHub-Actions-Cache wiederverwendet werden,
greift die neue Berechnung erst, wenn ein Titel neu beschafft wird; bei
1.500 Titeln/Tag ist das nach ~4 Tagen vollständig durchgelaufen.

**Bewusst NICHT umgesetzt:** Umbenennung des Feldes `avg_dollar_volume` (der
Name ist jetzt irreführend). `MarketSnapshot` nutzt `__slots__` und wird
gepickelt im GitHub-Actions-Cache abgelegt; eine Umbenennung machte den Cache
unlesbar und erzwänge einen vollständigen Neuabruf aller 5.000 Titel. Der
Kommentar an der Berechnungsstelle dokumentiert die Abweichung.

---

### Tests

| | vorher | nachher |
|---|---|---|
| Testanzahl | 155 | **178** |
| Status | grün | grün |

Neu: `tests/test_valuation.py` (9), `tests/test_structure_counts.py` (7),
`tests/test_liquidity.py` (7).

Zusätzlich als Integrationsprüfung auf 596 echten Titeln: keine
Berechnungsfehler, keine NaN/inf-Werte.
