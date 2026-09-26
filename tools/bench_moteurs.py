"""Bench comparatif de moteurs TTS sur le paragraphe FR de référence (M19.0).

Usage :
    python tools/bench_moteurs.py --moteurs cosyvoice,xtts \\
        --voix LeNarrateur --out output/bench_moteurs

Chaque moteur synthétise le même paragraphe ; on mesure coverage Whisper
(seuil 0.85), RTF, et on sauve les WAV pour l'écoute aveugle (grille hors
code, PROJET_FINE.md §3.4).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import bench_moteurs, multi, voix




def _entree_voix(nom):
    """Première entrée (wav+txt) de la voix, dict ou objet."""
    toutes = voix.load_voix()
    entrees = toutes.get(nom) if hasattr(toutes, "get") else toutes[nom]
    v = entrees[0] if isinstance(entrees, list) else entrees
    if isinstance(v, dict):
        return v.get("wav"), v.get("txt") or v.get("text")
    return getattr(v, "wav", None), getattr(v, "txt", getattr(v, "text", None))


def fabrique_cosyvoice(nom_voix, device, speed):
    model, sr = multi.load(device)
    wav, txt = _entree_voix(nom_voix)
    if not wav:
        raise SystemExit(f"voix inconnue : {nom_voix}")
    v = {"wav": wav, "txt": txt} if isinstance(wav, str) else (wav, txt)
    try:
        toutes = voix.load_voix()
        entrees = toutes.get(nom_voix)
        v = entrees[0] if isinstance(entrees, list) else entrees
    except Exception:
        pass

    def synth(texte):
        audio, _sr = multi.synth_bloc(v, texte, model, sr, speed=speed,
                                      verify=False)
        return audio, _sr
    return synth


def _patch_torchaudio_load():
    """torchaudio>=2.9 exige torchcodec (FFmpeg<=7) ; repli soundfile."""
    try:
        import torchaudio
        torchaudio.load((__import__("os").devnull,))
    except Exception:
        import soundfile as sf
        import torch

        def _load(uri, *a, **k):
            import numpy as np
            data, sr = sf.read(str(uri), always_2d=True, dtype='float32')
            return torch.from_numpy(np.ascontiguousarray(data.T)), sr

        torchaudio.load = _load


def fabrique_xtts(wav_ref, device):
    _patch_torchaudio_load()
    try:
        from TTS.api import TTS
    except ImportError:
        raise SystemExit("coqui-tts non installé (pip install coqui-tts)")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    def synth(texte):
        audio = tts.tts(texte, speaker_wav=wav_ref, language="fr")
        return audio, 24000
    return synth


def main(argv=None):
    p = argparse.ArgumentParser(description="Bench multi-moteurs M19.0")
    p.add_argument("--moteurs", default="cosyvoice",
                   help="liste : cosyvoice,xtts,fish (fish : à venir)")
    p.add_argument("--voix", default="LeNarrateur",
                   help="voix de référence (prompt + baseline cosyvoice)")
    p.add_argument("--wav-ref", default=None,
                   help="wav prompt pour xtts (défaut : wav de --voix)")
    p.add_argument("--device", default="cuda")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--out", default="output/bench_moteurs")
    args = p.parse_args(argv)

    moteurs = {}
    for nom in [m.strip() for m in args.moteurs.split(",") if m.strip()]:
        if nom == "cosyvoice":
            moteurs[nom] = fabrique_cosyvoice(args.voix, args.device,
                                              args.speed)
        elif nom == "xtts":
            wav_ref = args.wav_ref
            if wav_ref is None:
                wav_ref, _ = _entree_voix(args.voix)
            moteurs[nom] = fabrique_xtts(wav_ref, args.device)
        elif nom == "fish":
            raise SystemExit("moteur fish : fabrique à câbler (M19.0 en cours)")
        else:
            raise SystemExit(f"moteur inconnu : {nom}")

    verdict = bench_moteurs.comparer(
        moteurs, args.out,
        progress=lambda e: print(
            f"[{e['index']}/{e['total']}] {e['moteur']}: "
            f"coverage={e['coverage']} rtf={e['rtf']}", flush=True))
    out = Path(args.out)
    (out / "verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False))
    print(f"gagnant mesuré : {verdict['gagnant']} "
          f"(admissibles : {verdict['admissibles']})")
    print(f"WAV réécoutables dans {out} — écoute aveugle requise (§3.4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
