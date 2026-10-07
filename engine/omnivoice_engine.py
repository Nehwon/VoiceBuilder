"""Moteur OmniVoice (clonage zéro-shot wav + txt, 24 kHz natifs).

Contrat : ``load(device)`` renvoie ``(modele, 24000)`` (chargement unique),
``synthesize(...)`` renvoie un array mono float32. Branche omni : synthèse
directe en processus (transformers 5.x, image dédiée). Différences
assumées (V1) :

- pas de routage multilingue ``[en]`` : les marqueurs sont retirés et
  tout est normalisé en français (``text_fr.normalize``) ;
- pas de ``speed`` natif : une vitesse ≠ 1.0 est appliquée par
  étirement temporel (``librosa``) après synthèse ;
- pas de pré-cache de prompt (le modèle est déjà ~7× plus rapide).

Branche omni : pas de CosyVoice ici, donc pas de conflit transformers.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Optional

import numpy as np
import soundfile as sf

from . import bgm
from . import config
from . import text_fr

# --- Téléchargement du modèle : progression exposée à l'UI --------------------
# Au premier lancement, les poids (3,3 Go) se téléchargent en silence.
# ``precharger_async()`` lance le téléchargement en tâche de fond pendant que
# l'UI affiche une modale avec la progression réelle (au lieu d'une barre
# figée sur « Lancement de la génération... »).
_TELECHARGEMENT = {"en_cours": False, "pct": 0, "etape": "", "fichier": "",
                        "pct_fichier": 0, "erreur": None}
_JALONS_LOGGES: set = set()  # paliers globaux deja traces (log serveur)
_DERNIER_OCTET = 0.0  # monotonic() du dernier update (watchdog anti-blocage)


def _toucher():
    global _DERNIER_OCTET
    _DERNIER_OCTET = __import__("time").monotonic()


def _octets(n) -> str:
    """Quantité lisible (``1048576`` → ``1.0 Mo``) pour les labels sans total."""
    try:
        x = float(n or 0)
    except (TypeError, ValueError):
        return "0 o"
    for unite in ("o", "Ko", "Mo", "Go"):
        if x < 1024 or unite == "Go":
            return f"{x:.0f} {unite}" if unite == "o" else f"{x:.1f} {unite}"
        x /= 1024
    return f"{x:.1f} Go"
_VERROU_DL = threading.Lock()
_FIL_DL: threading.Thread | None = None


def progression_telechargement() -> dict:
    """État du téléchargement (copie : ``en_cours``, ``pct``, ``fichier``)."""
    with _VERROU_DL:
        return dict(_TELECHARGEMENT)


def _maj_progression(pct: float, fichier: str = "", en_cours: bool = True) -> None:
    with _VERROU_DL:
        _TELECHARGEMENT["pct"] = max(0, min(100, round(pct)))
        if fichier:
            _TELECHARGEMENT["fichier"] = fichier
        _TELECHARGEMENT["en_cours"] = en_cours


def _maj_global(pct: float, label: str) -> None:
    """Barre globale (tous fichiers) + jalon visible dans le log serveur."""
    _maj_progression(pct)
    with _VERROU_DL:
        _TELECHARGEMENT["etape"] = label
    palier = int(pct // 25) * 25
    if palier > 0 and palier not in _JALONS_LOGGES:
        _JALONS_LOGGES.add(palier)
        print(f"📦 modèle OmniVoice : {palier}% des fichiers ({label})", flush=True)


def _maj_fichier(pct: float, nom: str, pct_fichier: float | None = None) -> None:
    """Barre du fichier en cours + ligne log à chaque fichier terminé."""
    _toucher()
    with _VERROU_DL:
        _TELECHARGEMENT["fichier"] = nom or _TELECHARGEMENT["fichier"]
        _TELECHARGEMENT["pct_fichier"] = (
            max(0, min(100, round(pct_fichier))) if pct_fichier is not None
            else _TELECHARGEMENT["pct_fichier"])
        _TELECHARGEMENT["en_cours"] = True
    if (pct_fichier or 0) >= 100 and nom:
        with _VERROU_DL:
            cle = f"fichier:{nom}"
            if cle not in _JALONS_LOGGES:
                _JALONS_LOGGES.add(cle)
                print(f"📦 téléchargé : {nom}", flush=True)


class _TqdmProgression(__import__("tqdm").tqdm):
    """Barre tqdm réelle + report de l'avancement vers l'UI.

    Sous-classe du vrai ``tqdm`` (et non façade minimale) : huggingface_hub
    appelle ``refresh``/``close``/``set_description``/contexte, y compris pour
    les barres de reconstruction Xet — d'où le crash ``AttributeError:
    refresh`` avec la façade précédente.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("leave", False)
        super().__init__(*args, **kwargs)
        self._dernier_pct = -1.0

    def update(self, n=1):
        res = super().update(n)
        try:
            _toucher()
            total = self.total or 0
            desc = (getattr(self, "desc", "") or "").strip()
            bas = desc.lower()
            if bas.startswith("fetching"):
                # barre globale « Fetching 13 files » → libellé français
                if total > 0:
                    _maj_global(100.0 * (self.n or 0) / total,
                                f"Fichiers : {int(self.n or 0)}/{int(total)}")
                return res
            if bas.startswith("downloading"):
                nom = "Préparation…"
            elif bas.startswith("reconstructing"):
                nom = "Reconstruction…"
            else:
                nom = desc.split("/")[-1][:60] or "fichier…"
            if total > 0:
                pct = 100.0 * (self.n or 0) / total
                if pct - self._dernier_pct >= 0.5 or pct >= 100:
                    self._dernier_pct = pct
                    _maj_fichier(pct, f"{nom} — {_octets(self.n)} / {_octets(total)}",
                                 pct_fichier=pct)
            else:
                # total inconnu (Xet) : afficher les octets reçus, ça bouge
                _maj_fichier(-1, f"{nom} — {_octets(self.n)} reçus")
        except Exception:  # noqa: BLE001 — le report ne doit jamais casser le DL
            pass
        return res


def _repo_id() -> str:
    mid = config.OMNIVOICE_MODEL_ID
    return str(mid or config.OMNIVOICE_MODEL_DIR)


def modele_en_cache() -> bool:
    """Vrai si les poids sont déjà présents (aucun téléchargement requis)."""
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(repo_id=_repo_id(), local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 — absent du cache
        return False


_MOTS_XET = ("xet", "cas-server", "reconstruction", "middleware")
INACTIVITE_MAX_S = 180  # aucun octet depuis 3 min = flux bloqué
ESSAI_MAX_S = 1800  # plafond par essai, même si ça avance (reprise ensuite)


def _telecharger_une_fois(issue: dict) -> None:
    """Un appel ``snapshot_download`` ; l'exception éventuelle va dans ``issue``."""
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(
            repo_id=_repo_id(),
            token=config.hf_token(),
            tqdm_class=_TqdmProgression,
        )
    except Exception as exc:  # noqa: BLE001 — remonte via issue
        issue["erreur"] = exc


def _sans_xet() -> None:
    """Bascule le téléchargement sur S3 classique (contourne les erreurs CAS/Xet)."""
    import os

    import huggingface_hub.constants as _cst

    os.environ["HF_HUB_DISABLE_XET"] = "1"
    _cst.HF_HUB_DISABLE_XET = True  # relu à chaque appel (file_download)


try:
    _sans_xet()  # Xet désactivé par défaut (instable même avec clé)
except ImportError:  # hub absent (tests) : precacher échouera proprement
    pass
# opt-in explicite : VOICEBUILDER_XET=1 (variable d'environnement uniquement)


def precacher_modele(tentatives: int = 3) -> None:
    """Télécharge les poids (bloquant) avec progression ; sans effet si en cache.

    Robuste au premier lancement : téléchargement S3 classique (Xet désactivé
    par défaut — reconstruction CAS instable même avec clé), réessaie avec
    pause croissante, watchdog d'inactivité (3 min sans octet = nouvel essai).
    """
    import os
    import time

    if os.environ.get("VOICEBUILDER_XET") != "1":
        _sans_xet()
    else:
        print("📦 Xet activé (VOICEBUILDER_XET=1, expérimental)", flush=True)

    from huggingface_hub import snapshot_download

    if modele_en_cache():
        _maj_progression(100, en_cours=False)
        return
    with _VERROU_DL:
        _TELECHARGEMENT["erreur"] = None
    derniere: Exception | None = None
    for essai in range(1, tentatives + 1):
        print(f"📦 modèle OmniVoice : tentative {essai}/{tentatives}", flush=True)
        _maj_progression(0, f"connexion… (tentative {essai}/{tentatives})")
        _toucher()
        issue: dict = {}
        fil = threading.Thread(
            target=_telecharger_une_fois, args=(issue,), daemon=True)
        _toucher()
        fil.start()
        debut = time.monotonic()
        while fil.is_alive():
            fil.join(30)
            if not fil.is_alive():
                break
            inactif = time.monotonic() - _DERNIER_OCTET
            duree = time.monotonic() - debut
            if inactif > INACTIVITE_MAX_S:
                print(f"📦 flux bloqué (aucun octet depuis {int(inactif)} s), "
                      f"nouvel essai — la reprise continue", flush=True)
                break
            if duree > ESSAI_MAX_S:
                print(f"📦 essai de plus de {ESSAI_MAX_S // 60} min "
                      f"(ça avançait : {int(inactif)} s depuis le dernier octet), "
                      f"relève pour repartir sur une base saine", flush=True)
                break
        if fil.is_alive():
            derniere = TimeoutError("téléchargement interrompu (reprise au prochain essai)")
            if essai < tentatives:
                time.sleep(5)
            continue  # l'essai orphelin reste en fond (reprise au prochain)
        if "erreur" not in issue:
            _maj_progression(100, en_cours=False)
            return
        exc = issue["erreur"]
        derniere = exc
        bas = str(exc).lower()
        if any(m in bas for m in _MOTS_XET):
            _sans_xet()
            print("📦 repli S3 (sans Xet)…", flush=True)
            _maj_progression(0, "repli S3 (sans Xet)…")
            continue  # réessaie aussitôt sans Xet, sans consommer de pause
        if essai < tentatives:
            time.sleep(5 * essai)
    with _VERROU_DL:
        _TELECHARGEMENT["erreur"] = (
            f"{type(derniere).__name__} : {derniere}"[:300]
            + " — renseigne ta clé HF dans Réglages puis Réessayer.")
        _TELECHARGEMENT["en_cours"] = False
    assert derniere is not None
    raise derniere


def precharger_async() -> dict:
    """Lance ``precacher_modele`` en tâche de fond (une seule fois)."""
    global _FIL_DL
    with _VERROU_DL:
        en_cours = _TELECHARGEMENT["en_cours"]
        lance = _FIL_DL is not None and _FIL_DL.is_alive()
    if not en_cours and not lance and not modele_en_cache():
        with _VERROU_DL:
            _TELECHARGEMENT["en_cours"] = True
        _FIL_DL = threading.Thread(target=precacher_modele, daemon=True)
        _FIL_DL.start()
    return progression_telechargement()


# Marqueurs de langue inline (cf. text_fr.normalize_multilangue) : OmniVoice
# ne les consomme pas, on les retire avant synthèse (tout en français, V1).
_LANGUES_RE = re.compile(r"\[/?(?:en|fr)\]", re.IGNORECASE)

#: Fréquence native du modèle (imposée, cf. bench M19).
NATIVE_SR = 24000

# Modèle chargé une fois (singleton).
_model = None
_load_lock = threading.Lock()


def load(device: str = None) -> "tuple":
    """Charge (une fois) le modèle OmniVoice et renvoie (modele, 24000)."""
    global _model
    if _model is not None:
        return _model, NATIVE_SR
    with _load_lock:
        if _model is not None:
            return _model, NATIVE_SR
        device = device or config.DEFAULT_DEVICE
        from omnivoice import OmniVoice

        import torch

        precacher_modele()  # sans effet si déjà en cache (progression sinon)
        _model = OmniVoice.from_pretrained(
            str(config.OMNIVOICE_MODEL_DIR),
            device_map=device,
            dtype=torch.float16,
        )
    return _model, NATIVE_SR


def _preparer(text: str, prompt_text: str) -> tuple:
    """Normalisation FR + BGM (commune aux deux modes)."""
    text, veut_bgm = bgm.preparer_texte(text)
    prompt_text = bgm.preparer_texte(prompt_text)[0]
    text = text_fr.normalize(_LANGUES_RE.sub("", text))
    prompt_text = text_fr.normalize(_LANGUES_RE.sub("", prompt_text))
    return text, prompt_text, veut_bgm


def _post_traiter(audio: np.ndarray, speed: float, veut_bgm: bool,
                  sr_cible: int) -> np.ndarray:
    if speed and speed != 1.0:
        import librosa

        audio = np.asarray(librosa.effects.time_stretch(audio, rate=speed),
                           dtype=np.float32)
    if sr_cible != NATIVE_SR:
        import librosa

        audio = np.asarray(
            librosa.resample(audio, orig_sr=NATIVE_SR, target_sr=sr_cible),
            dtype=np.float32,
        )
    if veut_bgm:
        audio = bgm.appliquer(audio, sr_cible)
    return audio


def synthesize(
    text: str,
    prompt_wav: str,
    prompt_text: str,
    model: Optional[object] = None,
    sample_rate: Optional[int] = None,
    speed: float = config.DEFAULT_SPEED,
    stream: bool = False,
    out_sr: Optional[int] = None,
) -> np.ndarray:
    """Génère le TTS de ``text`` en clonant ``prompt_wav/prompt_text``.

    ``prompt_text`` = transcription **brute**. Renvoie un array mono
    float32 à ``out_sr`` Hz (``sample_rate`` du montage par défaut,
    rééchantillonné depuis les 24 kHz natifs si différent).
    """
    if model is None:
        model, _ = load()
    text, prompt_text, veut_bgm = _preparer(text, prompt_text)
    sr_cible = out_sr or sample_rate or NATIVE_SR

    audio = model.generate(text=text, ref_audio=str(prompt_wav),
                           ref_text=prompt_text)
    if isinstance(audio, (list, tuple)):
        audio = audio[0]
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    audio = np.asarray(audio, dtype=np.float32).squeeze()
    return _post_traiter(audio, speed, veut_bgm, sr_cible)


def save(audio: np.ndarray, sample_rate: int, path: str) -> None:
    sf.write(path, audio, sample_rate)

