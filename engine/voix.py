"""Gestion des voix : ``voix.txt`` et prompts CosyVoice3 (wav + txt).

Chaque voix = un couple ``.wav`` (échantillon à cloner) + ``.txt`` (sa
transcription exacte). Le fichier de listage a une entrée par ligne :

    [NomPersonnage] chemin.wav[, chemin.txt][, pause_pré][, vitesse][, max_chars]

Les chemins sont résolus par rapport au dossier projet ; en repli, par rapport au
dossier des voix (VOIX_DIR).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import config


def _strip_timestamps(line: str) -> str:
    """Retire les estampilles type ``[0000.00 - 0005.28]`` d'une transcription."""
    return re.sub(r"\[\s*\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*\]", "", line).strip()


@dataclass
class Voice:
    name: str
    wav: Path
    txt: Path
    pause: Optional[float] = None         # surcharge de la pause inter-bloc
    speed: Optional[float] = None
    max_block_chars: Optional[int] = None
    prompt_text: str = ""                 # transcription nettoyée

    @property
    def system_prompt(self) -> str:
        return f"{config.COSYVOICE3_SYSTEM_PROMPT}{self.prompt_text}"


class Voices:
    """Collection de voix chargées depuis un fichier ``voix.txt``."""

    def __init__(self, entries: List[Voice]):
        if not entries:
            raise ValueError("La liste des voix est vide.")
        self._by_name: Dict[str, Voice] = {v.name: v for v in entries}

    def names(self) -> List[str]:
        return list(self._by_name)

    def get(self, name: str) -> Voice:
        return self._by_name[name]

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())


def _resolve(path: str, bases) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    for b in bases:
        candidate = Path(b) / path
        if candidate.exists():
            return candidate
    return Path(bases[0]) / path


def collect_couples(dossier=None) -> List[tuple]:
    """Couples ``(wav, txt)`` d'un dossier (``*.wav`` + ``*.txt`` associé).

    Si ``dossier`` est absent, on prend ``config.VOIX_AUDIO_DIR``.
    """
    dossier = Path(dossier) if dossier is not None else config.VOIX_AUDIO_DIR
    if not dossier.is_dir():
        return []
    couples = []
    for wav in sorted(dossier.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        if txt.exists():
            couples.append((wav, txt))
    return couples


def default_nom(wav: Path) -> str:
    """Nom de voix par défaut à partir du nom de fichier ``.wav``.

    Retire un suffixe `_phrase_NNN` puis met en casse titre. L'utilisateur peut
    ensuite renommer via l'assistant.
    """
    import re
    base = re.sub(r"_phrase_?\d+$", "", wav.stem, flags=re.IGNORECASE)
    return base.replace("_", " ").strip().title() or wav.stem


def generer_voix_txt(dossier=None, out=None) -> Path:
    """Génère ``voix.txt`` (une entrée par couple wav+txt du dossier).

    Chaque ligne : ``[Nom] fichier.wav, fichier.txt`` (chemins du dossier).
    Ne génère que si ``voix.txt`` est absent, pour ne pas écraser l'existant.
    """
    dossier = Path(dossier) if dossier is not None else config.VOIX_AUDIO_DIR
    out = Path(out) if out else config.VOIX_FILE
    if out.exists():
        return out

    couples = collect_couples(dossier)
    lignes = []
    for wav, txt in couples:
        nom = default_nom(wav)
        lignes.append(f"[{nom}], {wav.name}, {txt.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")
    return out


def ecrire_voix_txt(entries, out=None) -> Path:
    """Écrit (écrase) ``voix.txt`` à partir d'une liste ``[(nom, wav, txt)]``."""
    out = Path(out) if out else config.VOIX_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    lignes = []
    for nom, wav, txt in entries:
        nom = (nom or "").strip()
        if not nom:
            continue
        lignes.append(f"[{nom}], {Path(wav).name}, {Path(txt).name}")
    out.write_text("\n".join(lignes) + ("\n" if lignes else ""), encoding="utf-8")
    return out


def load_voix(path: Optional[Path] = None, voix_dir: Optional[Path] = None) -> Voices:
    """Charge ``voix.txt`` et construit chaque voix (wav + transcription).

    Le champ ``txt`` est optionnel : s'il est absent, on le déduit du ``wav`` en
    remplaçant l'extension par ``.txt``. S'il reste l'inexistant, erreur.

    Les fichiers wav/txt sont cherchés, dans l'ordre, dans
    ``config.VOIX_SEARCH_DIRS`` (projet, racine des voix, dossier audio dédié).
    """
    path = Path(path) if path else config.VOIX_FILE
    bases = list(config.VOIX_SEARCH_DIRS)
    if voix_dir is not None:
        bases.insert(0, Path(voix_dir))
    if not path.exists():
        raise FileNotFoundError(f"Fichier de voix introuvable : {path}")

    voices: List[Voice] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                raise ValueError(f"Ligne de voix invalide : {line}")
            raw_name = parts[0]
            if not (raw_name.startswith("[") and raw_name.endswith("]")):
                raise ValueError(f"Le nom doit être entre crochets : {line}")
            name = raw_name[1:-1]

            wav = _resolve(parts[1], bases)
            if not wav.exists():
                raise FileNotFoundError(f"Voix wav introuvable : {wav}")

            txt: Optional[Path] = None
            if len(parts) >= 3 and parts[2]:
                txt = _resolve(parts[2], bases)
            if txt is None:
                txt = Path(str(wav)[: str(wav).rfind(".")] + ".txt")
            if not txt.exists():
                raise ValueError(f"Pas de transcription (.txt) pour la voix : {name}")

            with open(txt, encoding="utf-8") as tf:
                transcription = "\n".join(
                    _strip_timestamps(l) for l in tf if l.strip()
                ).strip()

            voice = Voice(name=name, wav=wav, txt=txt, prompt_text=transcription)
            if len(parts) >= 4 and parts[3]:
                voice.pause = float(parts[3])
            if len(parts) >= 5 and parts[4]:
                voice.speed = float(parts[4])
            if len(parts) >= 6 and parts[5]:
                voice.max_block_chars = int(parts[5])

            voices.append(voice)

    return Voices(voices)