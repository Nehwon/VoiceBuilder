#!/usr/bin/env python3
"""M18.1 — Kit dataset LoRA (Palier 1, préparation).

Usage :
    python tools/preparer_lora.py --voix NOM --audio long1.wav [long2.wav ...]
        [--text corrigé.txt] [--out dataset/lora] [--tokens]

Depuis de longs enregistrements (+ transcription Whisper horodatée, ou
`--text` corrigé manuellement au format kaldi) : segments 5–12 s (pic VRAM
réduit), transcriptions exactes, dédup, split train/dev ; sortie kaldi
(`wav.scp`, `text`, `utt2spk`) + `manifest.json`. Avec `--tokens` : extraction
des speech tokens + listes parquet au format `vendor/CosyVoice/tools/`.

Refuse < 15 min effectives (gain marginal vs zéro-shot, `PROJET_FINE.md` §3.2).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DUREE_MIN, DUREE_MAX = 5.0, 12.0  # segments courts : pic VRAM réduit (M18.2)
SEUIL_15MIN = 15 * 60             # en deçà : gain marginal vs zéro-shot
RATIO_DEV = 0.05
SR_CIBLE = 16000                  # convention datasets CosyVoice (fbank 16 kHz)
INSTRUCT_DEFAUT = "You are a helpful assistant.<|endofprompt|>"  # recette officielle


def slug(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", nom).strip("_") or "voix"


def normaliser_texte(s: str) -> str:
    """Minuscules, ponctuation/accents retirés (clé de dédup)."""
    import unicodedata
    s = re.sub(r"[^\w\s]", "", s).lower()
    s = unicodedata.normalize("NFD", s)
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def fusionner_segments(segs: list[dict]) -> list[dict]:
    """Fusionne les voisins courts (< min) ; coupe les longs (> max) au milieu.

    Entrée : ``[{start, end, text}]`` triés. Sortie : mêmes champs, durées
    dans [min, max] (sauf reste final < min fusionné au précédent, ou segment
    isolé < min conservé tel quel).
    """
    fusionnes: list[dict] = []
    for s in segs:
        if fusionnes and fusionnes[-1]["end"] - fusionnes[-1]["start"] < DUREE_MIN:
            p = fusionnes[-1]
            p["end"] = s["end"]
            p["text"] = f"{p['text']} {s['text']}".strip()
        else:
            fusionnes.append(dict(s))
    decoupes: list[dict] = []
    for s in fusionnes:
        d = s["end"] - s["start"]
        if d <= DUREE_MAX:
            decoupes.append(s)
            continue
        # coupe récursive au milieu (texte réparti au prorata des mots)
        mots = s["text"].split()
        mid = (s["start"] + s["end"]) / 2
        n = max(1, round(len(mots) * (mid - s["start"]) / d))
        a = {"start": s["start"], "end": mid, "text": " ".join(mots[:n])}
        b = {"start": mid, "end": s["end"], "text": " ".join(mots[n:]) or s["text"]}
        decoupes.extend(fusionner_segments([a, b]))
    return decoupes


def filtrer_silence(segs: list[dict], audio: np.ndarray, sr: int,
                    seuil_db: float = -40.0, max_silence: float = 0.5) -> list[dict]:
    """Écarte les segments à dominante silencieuse (énergie, trames 20 ms)."""
    n = max(1, int(sr * 0.02))
    gardes = []
    for s in segs:
        a = audio[int(s["start"] * sr):int(s["end"] * sr)]
        if len(a) < n:
            continue
        tr = a[: len(a) // n * n].reshape(-1, n)
        e = np.sqrt(np.mean(tr ** 2, axis=1))
        part = float(np.mean(e < 10.0 ** (seuil_db / 20.0)))
        if part <= max_silence and s["text"].strip():
            gardes.append(s)
    return gardes


def dedup(segs: list[dict]) -> list[dict]:
    """Déduplique sur le texte normalisé (garde la 1re occurrence)."""
    vus, uniques = set(), []
    for s in segs:
        cle = normaliser_texte(s["text"])
        if not cle or cle in vus:
            continue
        vus.add(cle)
        uniques.append(s)
    return uniques


def split_train_dev(segs: list[dict], ratio: float = RATIO_DEV,
                    seed: int = 7) -> tuple[list[dict], list[dict]]:
    """Split dev ~ratio de la durée (min 3 segments si possible)."""
    if len(segs) < 4:
        return segs, []
    rng = random.Random(seed)
    idx = list(range(len(segs)))
    rng.shuffle(idx)
    total = sum(s["end"] - s["start"] for s in segs)
    cible = total * ratio
    pris, duree = set(), 0.0
    for i in idx:
        if duree >= cible and len(pris) >= 3:
            break
        pris.add(i)
        duree += segs[i]["end"] - segs[i]["start"]
    dev = [segs[i] for i in sorted(pris)]
    train = [s for j, s in enumerate(segs) if j not in pris]
    return train, dev


def appliquer_texte_corrige(segs: list[dict], textes: dict[str, str]) -> list[dict]:
    """Remplace les transcriptions par un fichier corrigé (utt → texte).

    Erreur si un utt manque : pas de mélange corrigé/auto.
    """
    for s in segs:
        if s["utt"] not in textes:
            raise ValueError(f"Transcription manquante pour {s['utt']} dans --text")
        s["text"] = textes[s["utt"]].strip()
    return segs


def lire_texte_kaldi(path: Path) -> dict[str, str]:
    """Lit un fichier kaldi `text` (utt + transcription)."""
    textes = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        utt, _, txt = ln.partition(" ")
        textes[utt.strip()] = txt.strip()
    return textes


def ecrire_kaldi(dossier: Path, segs: list[dict], spk: str) -> None:
    """Écrit `wav.scp`, `text`, `utt2spk` (+ `instruct` par défaut, requis par
    le forward CosyVoice3) — triés par utt."""
    dossier.mkdir(parents=True, exist_ok=True)
    segs = sorted(segs, key=lambda s: s["utt"])
    (dossier / "wav.scp").write_text(
        "".join(f"{s['utt']} {s['wav']}\n" for s in segs), encoding="utf-8")
    (dossier / "text").write_text(
        "".join(f"{s['utt']} {s['text']}\n" for s in segs), encoding="utf-8")
    (dossier / "utt2spk").write_text(
        "".join(f"{s['utt']} {spk}\n" for s in segs), encoding="utf-8")
    (dossier / "instruct").write_text(
        "".join(f"{s['utt']} {INSTRUCT_DEFAUT}\n" for s in segs), encoding="utf-8")


def charger_audio(path: Path) -> tuple[np.ndarray, int]:
    """Charge en mono float32 (resample 16 kHz si besoin)."""
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(axis=1).astype(np.float32)
    if sr != SR_CIBLE:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=SR_CIBLE).astype(np.float32)
        sr = SR_CIBLE
    return y, sr


def transcrire(audio: np.ndarray, sr: int, lang: str = "fr") -> list[dict]:
    """Transcription horodatée Whisper → [{start, end, text}]."""
    import whisper
    from engine import config
    y = audio
    if sr != SR_CIBLE:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=SR_CIBLE).astype(np.float32)
    model = whisper.load_model(config.WHISPER_MODEL, device="cuda")
    res = model.transcribe(y, language=lang, fp16=False)
    return [{"start": float(s["start"]), "end": float(s["end"]),
             "text": s["text"].strip()} for s in res.get("segments", [])
            if s["text"].strip()]


def lancer(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Échec {' '.join(cmd[:3])}… :\n{r.stderr[-2000:]}")


def extraire_tokens_parquet(racine: Path, onnx: str, threads: int = 8) -> dict:
    """Tokens + parquet par split (format vendor/CosyVoice/tools/)."""
    from engine import config as _cfg
    onnx = onnx or str(Path(_cfg.COSYVOICE_MODEL_DIR) / "speech_tokenizer_v3.onnx")
    vendor = Path(_cfg.COSYVOICE_ROOT) / "tools"
    sorties = {}
    for split in ("train", "dev"):
        kaldi = racine / "kaldi" / split
        if not (kaldi / "wav.scp").exists():
            continue
        lancer([sys.executable, str(vendor / "extract_speech_token.py"),
                "--dir", str(kaldi), "--onnx_path", onnx,
                "--num_thread", str(threads)])
        des = racine / f"parquet_{split}"
        des.mkdir(parents=True, exist_ok=True)
        lancer([sys.executable, str(vendor / "make_parquet_list.py"),
                "--src_dir", str(kaldi), "--des_dir", str(des),
                "--num_utts_per_parquet", "1000", "--num_processes", "1"])
        sorties[split] = {"kaldi": str(kaldi), "parquet": str(des)}
    return sorties


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M18.1 — Kit dataset LoRA")
    ap.add_argument("--voix", required=True, help="Nom de la voix / personnage")
    ap.add_argument("--audio", nargs="+", required=True,
                    help="Enregistrements longs (wav/mp3/flac)")
    ap.add_argument("--text", default=None,
                    help="Transcriptions corrigées (kaldi text, utt → texte)")
    ap.add_argument("--out", default=None, help="Racine datasets (défaut: dataset/lora)")
    ap.add_argument("--tokens", action="store_true",
                    help="Extraire tokens + parquet (GPU, onnx CosyVoice3)")
    ap.add_argument("--onnx", default=None, help="speech_tokenizer onnx (défaut: modèle)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    from engine import config
    spk = slug(args.voix)
    racine = (Path(args.out) if args.out
              else Path(config.PROJECT_ROOT) / "dataset" / "lora" / spk)
    racine.mkdir(parents=True, exist_ok=True)

    # 1) transcription horodatée de chaque source
    bruts: list[dict] = []
    for chemin in args.audio:
        p = Path(chemin)
        if not p.exists():
            print(f"❌ Audio introuvable : {p}")
            return 1
        print(f"Transcription de {p.name}…")
        y, sr = charger_audio(p)
        for s in transcrire(y, sr):
            s["audio_id"] = p.stem
            bruts.append((s, y, sr))
    bruts.sort(key=lambda t: (t[0].get("audio_id", ""), t[0]["start"]))

    # 2) découpe 5–12 s par source, puis WAV 16 kHz
    seg_dir = racine / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    segs: list[dict] = []
    idx = 0
    for audio_id in dict.fromkeys(s.get("audio_id", "") for s, _, _ in bruts):
        groupe = [s for s, _, _ in bruts if s.get("audio_id", "") == audio_id]
        y = next(y for s, y, _ in bruts if s.get("audio_id", "") == audio_id)
        sr = next(sr for s, _, sr in bruts if s.get("audio_id", "") == audio_id)
        for s in filtrer_silence(fusionner_segments(groupe), y, sr):
            idx += 1
            utt = f"{spk}_{idx:05d}"
            a = y[int(s["start"] * sr):int(s["end"] * sr)]
            wav = seg_dir / f"{utt}.wav"
            import soundfile as sf
            sf.write(str(wav), a, sr)
            segs.append({"utt": utt, "start": s["start"], "end": s["end"],
                         "text": s["text"], "wav": str(wav.resolve())})

    # 3) textes corrigés éventuels, dedup, gate 15 min
    if args.text:
        segs = appliquer_texte_corrige(segs, lire_texte_kaldi(Path(args.text)))
    segs = dedup(segs)
    import soundfile as sf
    duree = 0.0
    for s in segs:
        duree += sf.info(s["wav"]).duration
    print(f"{len(segs)} segments, {duree / 60:.1f} min effectives")
    if duree < SEUIL_15MIN:
        print(f"❌ {duree / 60:.1f} min < 15 min : gain marginal vs zéro-shot "
              f"(PROJET_FINE.md §3.2) — ajoute des sources.")
        return 2

    # 4) split + kaldi + manifest
    train, dev = split_train_dev(segs, seed=args.seed)
    ecrire_kaldi(racine / "kaldi" / "train", train, spk)
    if dev:
        ecrire_kaldi(racine / "kaldi" / "dev", dev, spk)
    manifest = {
        "voix": args.voix, "spk": spk, "segments": len(segs),
        "duree_min": round(duree / 60, 1),
        "train": len(train), "dev": len(dev),
        "kaldi": str((racine / "kaldi").resolve()),
    }
    if args.tokens:
        print("Extraction des tokens + parquet…")
        manifest["splits"] = extraire_tokens_parquet(racine, args.onnx, args.threads)
    (racine / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dataset prêt : {racine} "
          f"({len(train)} train / {len(dev)} dev, manifest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
