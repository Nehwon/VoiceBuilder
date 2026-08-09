#!/usr/bin/env python3
"""M2 — Assistant de création d'une voix à partir d'un fichier audio source.

Extrait le segment ``[start, stop]`` du fichier, le sauvegarde en `.wav` dans
``voix/``, le transcrit via Whisper en ``.txt``, puis ajoute l'entrée à
``voix.txt``.

Usage :
    python -m tools.create_voix SOURCE --nom LeNarrateur --start 12.5 --stop 30
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import config, verifier


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "voix"


def extract_segment(src: str, start: float, stop: float):
    """Découpe ``[start, stop]`` d'un fichier -> (audio float32 mono, sr)."""
    import soundfile as sf
    data, sr = sf.read(src, dtype="float32")
    i0, i1 = int(start * sr), int(stop * sr)
    if i0 < 0 or i1 > len(data) or i0 >= i1:
        raise ValueError(
            f"Segment [{start}..{stop}] s hors des bornes (durée = {len(data)/sr:.1f} s)"
        )
    return data[i0:i1], sr


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Transcription d'une voix (wav + txt)")
    parser.add_argument("source", help="Fichier audio source (wav/flac/…)")
    parser.add_argument("--nom", required=True, help="Nom du personnage (utilisé entre [ ])")
    parser.add_argument("--start", type=float, required=True, help="Début du segment (s)")
    parser.add_argument("--stop", type=float, required=True, help="Fin du segment (s)")
    parser.add_argument("--out", default=None, help="WAV de sortie (défaut: voix/<slug>.wav)")
    parser.add_argument("--voix", default=None, help="Fichier voix.txt à enrichir")
    parser.add_argument("--no-transcribe", action="store_true", help="Ne pas transcrire")
    parser.add_argument("--lang", default=None,
                        help="Langue Whisper (défaut: config.WHISPER_LANG)")
    parser.add_argument("--timestamps", action="store_true",
                        help="Sortie horodatée `[0000.00 - 0005.28] texte` par segment")
    parser.add_argument("--max-sec", type=float, default=30.0,
                        help="Avertit si le segment dépasse cette durée (défaut 30 s)")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    out = Path(args.out) if args.out else config.VOIX_DIR / f"{slugify(args.nom)}.wav"
    if not out.is_absolute():
        out = config.VOIX_DIR / out
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Extraction [{args.start}..{args.stop}] s de {args.source}")
    audio, sr = extract_segment(args.source, args.start, args.stop)
    duree = len(audio) / sr
    print(f"  segment : {duree:.2f} s @ {sr} Hz")

    if args.max_sec and duree > args.max_sec:
        print(f"⚠️  Segment de {duree:.1f} s > {args.max_sec:.0f} s : "
              f"fidélité du clone réduite sur les segments longs.",
              file=sys.stderr)

    import soundfile as sf
    sf.write(str(out), audio, sr)
    print(f"  wav : {out}")

    text = ""
    if not args.no_transcribe:
        lang = args.lang or config.WHISPER_LANG
        print(f"Transcription (Whisper, {lang})…")
        if args.timestamps:
            text = verifier.transcribe_timestamped(audio, sr, lang=lang).strip()
        else:
            text = verifier.transcribe(audio, sr, lang=lang).strip()
        print(f"  texte : {text!r}")

    txt = out.with_suffix(".txt")
    txt.write_text(text + "\n" if text else "", encoding="utf-8")
    print(f"  txt : {txt}")

    voix_file = Path(args.voix) if args.voix else config.VOIX_FILE
    if not voix_file.exists():
        voix_file.touch()
    rel = out.relative_to(config.VOIX_DIR) if out.is_relative_to(config.VOIX_DIR) else out
    with voix_file.open("a", encoding="utf-8") as f:
        f.write(f"[{args.nom}], {rel}\n")
    print(f"  voix.txt : +[{args.nom}], {rel}")

    print("\nFait. Vérifie la transcription (échantillon <= ~30 s, timbre net).")
    return 0


if __name__ == "__main__":
    sys.exit(main())