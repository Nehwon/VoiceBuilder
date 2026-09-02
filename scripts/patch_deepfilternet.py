#!/usr/bin/env python3
"""Patche le paquet installé DeepFilterNet (df/io.py) pour torchaudio >= 2.9.

DeepFilterNet 0.5.x importe ``torchaudio.backend.common.AudioMetaData``, API
supprimée dans les torchaudio récents (>= 2.9). VoiceBuilder embarque
torchaudio 2.11 : sans ce patch, ``import df`` échoue.

Le patch réécrit ``df/io.py`` (chargement/sauvegarde via ``soundfile`` au lieu
de ``torchaudio``) — fonctionnellement équivalent, et idempotent (un marqueur
évite de re-patcher).

Usage :
    python scripts/patch_deepfilternet.py [chemin_site_packages]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MARQUEUR = "# Patched by VoiceBuilder (patch_deepfilternet.py)"

_CONTENU = '''{marqueur}
# Remplace les appels torchaudio (API supprimée dans torchaudio>=2.9 :
# torchaudio.backend.common) par soundfile / torchaudio.functional.resample.
import os
from typing import Optional, Tuple, Union

import numpy as np
import soundfile as sf
import torch
from torch import Tensor

try:
    from torchaudio.functional import resample as _ta_resample
except Exception:  # pragma: no cover  (torchaudio très ancien)
    _ta_resample = None


class AudioMetaData:
    """Métadonnées audio (compat API torchaudio supprimée)."""

    __slots__ = ("sample_rate", "num_frames", "num_channels",
                 "bits_per_sample", "encoding")

    def __init__(self, sample_rate, num_frames, num_channels,
                 bits_per_sample, encoding):
        self.sample_rate = int(sample_rate)
        self.num_frames = int(num_frames)
        self.num_channels = int(num_channels)
        self.bits_per_sample = int(bits_per_sample)
        self.encoding = str(encoding)

    def __repr__(self):
        return (f"AudioMetaData(sample_rate={{self.sample_rate}}, "
                f"num_frames={{self.num_frames}}, "
                f"num_channels={{self.num_channels}}, "
                f"bits_per_sample={{self.bits_per_sample}}, "
                f"encoding={{self.encoding}})")


def _resample_tensor(audio: Tensor, orig_sr: int, new_sr: int) -> Tensor:
    if _ta_resample is not None:
        return _ta_resample(audio, orig_sr, new_sr)
    import librosa
    return torch.from_numpy(
        librosa.resample(audio.cpu().numpy(), orig_sr=orig_sr, target_sr=new_sr)
    )


def load_audio(file: str, sr: Optional[int] = None, verbose=True,
               **kwargs) -> Tuple[Tensor, AudioMetaData]:
    """Charge un fichier audio en float32 [C, T], ré-échantillonné si besoin."""
    info = sf.info(file)
    meta = AudioMetaData(info.samplerate, info.frames, info.channels, 0,
                         str(info.subtype))
    data, orig_sr = sf.read(file, dtype="float32", always_2d=True)
    audio = torch.from_numpy(data.T).contiguous()          # [C, T]
    if sr is not None and orig_sr != sr:
        audio = _resample_tensor(audio, orig_sr, sr)
    return audio, meta


def save_audio(file, audio, sr, output_dir: Optional[str] = None,
               suffix: Optional[str] = None, log=False,
               dtype=torch.int16):
    outpath = file
    if suffix is not None:
        base, ext = os.path.splitext(file)
        outpath = f"{{base}}_{{suffix}}{{ext}}"
    if output_dir is not None:
        outpath = os.path.join(output_dir, os.path.basename(outpath))
    audio = torch.as_tensor(audio)
    if audio.ndim == 1:
        audio = audio.unsqueeze_(0)
    if dtype == torch.int16 and audio.dtype != torch.int16:
        audio = (audio * (1 << 15)).to(torch.int16)
    elif dtype == torch.float32 and audio.dtype != torch.float32:
        audio = audio.to(torch.float32) / (1 << 15)
    sf.write(outpath, audio.squeeze(0).cpu().numpy(), sr)


def resample(audio: Tensor, orig_sr: int, new_sr: int,
             method="sinc_fast") -> Tensor:
    """Ré-échantillonne un tenseur audio [C, T]."""
    return _resample_tensor(audio, orig_sr, new_sr)
'''.format(marqueur=_MARQUEUR)


def _localiser_df() -> Path:
    """Renvoie le chemin du paquet ``df`` installé (sans l'importer)."""
    spec = importlib.util.find_spec("df")
    if spec is None or spec.submodule_search_locations is None:
        # paquet absent : rien à patcher
        return Path("/nonexistent")
    return Path(next(iter(spec.submodule_search_locations)))


def main(argv=None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if argv:
        df_dir = Path(argv[0])
    else:
        df_dir = _localiser_df()
    cible = df_dir / "io.py"
    if not cible.exists():
        print(f"→ df introuvable ({cible}) — paquet non installé, ignoré.")
        return 0
    contenu = cible.read_text(encoding="utf-8")
    if _MARQUEUR in contenu:
        print("→ df/io.py déjà patché, ignoré.")
        return 0
    if "torchaudio.backend.common" not in contenu:
        print(f"→ df/io.py inattendu ({cible}) — on écrit quand même la version sûre.")
    cible.write_text(_CONTENU, encoding="utf-8")
    print("→ df/io.py patché (soundfile au lieu de torchaudio.backend.common).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
