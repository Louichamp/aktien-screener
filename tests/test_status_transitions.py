"""Status-Uebergaenge, Volumenbestaetigung und Hysterese (§33).

Der Status ist eine Aussage ueber den aktuellen Zustand, keine Bewertung. Damit
er nicht bei jedem Rauschen kippt, liegen drei Schutzmechanismen davor:

  1. Strukturvalidator  — nur erlaubte Uebergaenge (ALLOWED)
  2. Volumenbestaetigung — „Breakout aktiv" nur ab 1,4x Durchschnittsvolumen
  3. Hysterese          — ein Kandidat muss 2 Laeufe in Folge bestehen

Harte Ereignisse (Disqualifikation, bestaetigter Breakout) umgehen die
Hysterese bewusst: Eine Disqualifikation soll nicht zwei Laeufe warten.
"""
from __future__ import annotations

from screener.status import (ALLOWED, Status, StatusMemory, TransitionValidator)


def _v() -> TransitionValidator:
    return TransitionValidator(confirm_runs=2, breakout_volume=1.4)


# --------------------------------------------------------------------------- #
#  Erstbewertung und Selbst-Uebergang
# --------------------------------------------------------------------------- #
def test_erstbewertung_uebernimmt_den_kandidaten():
    mem, geaendert, note = _v().validate(StatusMemory(), Status.BODENBILDUNG,
                                         volume_ratio=1.0, hard=False)
    assert mem.status == Status.BODENBILDUNG and geaendert
    assert note == "Initialer Status"


def test_gleicher_status_ist_keine_aenderung():
    mem, geaendert, _ = _v().validate(StatusMemory(Status.BODENBILDUNG),
                                      Status.BODENBILDUNG,
                                      volume_ratio=1.0, hard=False)
    assert not geaendert and mem.pending_count == 0


# --------------------------------------------------------------------------- #
#  Hysterese
# --------------------------------------------------------------------------- #
def test_ein_einzelner_lauf_reicht_nicht():
    mem, geaendert, note = _v().validate(
        StatusMemory(Status.BODENBILDUNG), Status.AUSBRUCH_VORBEREITET,
        volume_ratio=1.0, hard=False)
    assert not geaendert
    assert mem.status == Status.BODENBILDUNG
    assert mem.pending == Status.AUSBRUCH_VORBEREITET and mem.pending_count == 1
    assert note and "Hysterese" in note


def test_zwei_laeufe_in_folge_setzen_den_status():
    v = _v()
    mem, _, _ = v.validate(StatusMemory(Status.BODENBILDUNG),
                           Status.AUSBRUCH_VORBEREITET,
                           volume_ratio=1.0, hard=False)
    mem2, geaendert, _ = v.validate(mem, Status.AUSBRUCH_VORBEREITET,
                                    volume_ratio=1.0, hard=False)
    assert geaendert and mem2.status == Status.AUSBRUCH_VORBEREITET
    assert mem2.pending is None and mem2.pending_count == 0


def test_wechselnder_kandidat_setzt_den_zaehler_zurueck():
    """Sonst wuerde Rauschen ueber mehrere verschiedene Kandidaten hinweg
    einen Wechsel erzwingen."""
    v = _v()
    mem, _, _ = v.validate(StatusMemory(Status.BODENBILDUNG),
                           Status.AUSBRUCH_VORBEREITET,
                           volume_ratio=1.0, hard=False)
    assert mem.pending_count == 1
    mem2, geaendert, _ = v.validate(mem, Status.BODEN_ABWARTEN,
                                    volume_ratio=1.0, hard=False)
    assert not geaendert and mem2.pending_count == 1
    assert mem2.pending == Status.BODEN_ABWARTEN


# --------------------------------------------------------------------------- #
#  Volumenbestaetigung des Breakouts
# --------------------------------------------------------------------------- #
def test_breakout_ohne_volumen_wird_nicht_bestaetigt():
    mem, geaendert, note = _v().validate(
        StatusMemory(Status.AUSBRUCH_VORBEREITET), Status.BREAKOUT_AKTIV,
        volume_ratio=1.0, hard=False)
    assert not geaendert and mem.status == Status.AUSBRUCH_VORBEREITET
    assert note and "Volumen" in note


def test_breakout_ohne_volumendaten_wird_nicht_bestaetigt():
    """Fehlendes Volumen darf nicht als Bestaetigung durchgehen."""
    _, geaendert, _ = _v().validate(
        StatusMemory(Status.AUSBRUCH_VORBEREITET), Status.BREAKOUT_AKTIV,
        volume_ratio=None, hard=False)
    assert not geaendert


def test_breakout_mit_volumen_greift_sofort_ohne_hysterese():
    mem, geaendert, note = _v().validate(
        StatusMemory(Status.AUSBRUCH_VORBEREITET), Status.BREAKOUT_AKTIV,
        volume_ratio=1.6, hard=False)
    assert geaendert and mem.status == Status.BREAKOUT_AKTIV
    assert note == "Hartes Ereignis"


def test_schwelle_liegt_bei_1_4():
    v = _v()
    _, unter, _ = v.validate(StatusMemory(Status.AUSBRUCH_VORBEREITET),
                             Status.BREAKOUT_AKTIV, volume_ratio=1.39, hard=False)
    _, drueber, _ = v.validate(StatusMemory(Status.AUSBRUCH_VORBEREITET),
                               Status.BREAKOUT_AKTIV, volume_ratio=1.41, hard=False)
    assert not unter and drueber


# --------------------------------------------------------------------------- #
#  Struktureller Validator
# --------------------------------------------------------------------------- #
def test_unzulaessiger_uebergang_wird_abgelehnt():
    mem, geaendert, note = _v().validate(
        StatusMemory(Status.BODEN_ABWARTEN), Status.POSITION_VERWALTEN,
        volume_ratio=1.0, hard=False)
    assert not geaendert and mem.status == Status.BODEN_ABWARTEN
    assert note and "unzulaessig" in note.lower().replace("ä", "ae")


def test_vermeiden_ist_aus_jedem_status_erreichbar():
    """Eine Disqualifikation darf nie an der Uebergangstabelle scheitern.

    Der Selbstfall (`Vermeiden` -> `Vermeiden`) ist ausgenommen: Dort meldet
    der Validator korrekt „keine Aenderung", weil der Status bereits gilt.
    """
    for davor in ALLOWED:
        if davor == Status.VERMEIDEN:
            continue
        mem, geaendert, _ = _v().validate(StatusMemory(davor), Status.VERMEIDEN,
                                          volume_ratio=1.0, hard=True)
        assert geaendert and mem.status == Status.VERMEIDEN, f"blockiert aus {davor}"


def test_vermeiden_bleibt_vermeiden():
    mem, geaendert, _ = _v().validate(StatusMemory(Status.VERMEIDEN),
                                      Status.VERMEIDEN, volume_ratio=1.0, hard=True)
    assert not geaendert and mem.status == Status.VERMEIDEN


def test_uebergangstabelle_kennt_nur_gueltige_status():
    gueltig = {v for k, v in vars(Status).items() if not k.startswith("_")}
    for davor, ziele in ALLOWED.items():
        assert davor in gueltig
        assert ziele <= gueltig, f"unbekanntes Ziel in {davor}"


def test_jeder_status_hat_einen_ausweg():
    """Kein Zustand darf eine Sackgasse sein."""
    for davor, ziele in ALLOWED.items():
        assert ziele, f"{davor} hat keinen erlaubten Folgestatus"
