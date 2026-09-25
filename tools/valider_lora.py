#!/usr/bin/env python3
"""M18.3 - Validation LoRA, protocole PROJET_FINE 3.4."""
import argparse, json, random, shutil, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
from engine import config, verifier
from engine.lora import registre
TEXTE_REFERENCE_FR = (
"Le vent poussait des nuages gris sur la vallee.")
def charger_wav(path):
    a, sr = sf.read(str(path), dtype="float32")
    return np.asarray(a, dtype=np.float32), int(sr)
def preparer_aveugle(zero_wav, lora_wav, out_dir, seed):
    rng = random.Random(seed)
    cotes = ["zero", "lora"]
    rng.shuffle(cotes)
    mapping = {"A": cotes[0], "B": cotes[1]}
    out_dir.mkdir(parents=True, exist_ok=True)
    src = {"zero": zero_wav, "lora": lora_wav}
    shutil.copyfile(src[mapping["A"]], out_dir / "A.wav")
    shutil.copyfile(src[mapping["B"]], out_dir / "B.wav")
    return mapping
def compter_votes(votes, mapping):
    inv = {v: k for k, v in mapping.items()}
    res = {"zero": 0, "lora": 0, "nuls": 0}
    for nom, choix in votes.items():
        cote = mapping.get(str(choix).strip().upper())
        if cote in res:
            res[cote] += 1
        else:
            res["nuls"] += 1
    return res
def decider(cov_lora, n_lora, n_zero, n_auditeurs, seuil, min_auditeurs):
    if n_auditeurs < min_auditeurs:
        return False, "auditeurs insuffisants"
    if cov_lora < seuil:
        return False, "coverage sous seuil"
    if n_lora <= n_zero:
        return False, "aveugle non gagne"
    return True, "gagnant"
def construire_argparser():
    ap = argparse.ArgumentParser(description="M18.3 validation LoRA 3.4")
    ap.add_argument("--voix", required=True)
    ap.add_argument("--lora", required=True, help="Dossier poids LoRA candidat")
    ap.add_argument("--audio-zero", required=True)
    ap.add_argument("--audio-lora", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seuil", type=float, default=None)
    ap.add_argument("--min-auditeurs", type=int, default=2)
    ap.add_argument("--votes", default=None)
    ap.add_argument("--rtf-zero", type=float, default=None)
    ap.add_argument("--rtf-lora", type=float, default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--etage", default=None)
    ap.add_argument("--dataset-racine", default=None)
    ap.add_argument("--enregistrer", action="store_true")
    return ap
def main(argv=None):
    ap = construire_argparser()
    args = ap.parse_args(argv)
    seuil = args.seuil if args.seuil is not None else config.VERIFY_THRESHOLD
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    z_audio, z_sr = charger_wav(args.audio_zero)
    l_audio, l_sr = charger_wav(args.audio_lora)
    if z_sr != l_sr:
        print("sr differents", file=sys.stderr)
        return 2
    texte = TEXTE_REFERENCE_FR
    cov_zero = float(verifier.coverage(texte, z_audio, z_sr))
    cov_lora = float(verifier.coverage(texte, l_audio, l_sr))
    mapping = preparer_aveugle(args.audio_zero, args.audio_lora, out, args.seed)
    (out / "mapping_secret.json").write_text(json.dumps(mapping, indent=2))
    (out / "grille_ecoute.json").write_text(json.dumps({"consigne": "Ecoute aveugle: choisir A ou B", "votes": {}}, ensure_ascii=False, indent=2))
    votes = {}
    if args.votes:
        votes = json.loads(Path(args.votes).read_text(encoding="utf-8"))
    comptes = compter_votes(votes, mapping)
    n_aud = len(votes)
    gagnant, motif = decider(cov_lora, comptes["lora"], comptes["zero"], n_aud, seuil, args.min_auditeurs)
    rapport = {"voix": args.voix, "lora": args.lora, "seuil": seuil}
    rapport["zero"] = {"coverage": cov_zero, "rtf": args.rtf_zero}
    rapport["lora"] = {"coverage": cov_lora, "rtf": args.rtf_lora}
    rapport["aveugle"] = {"mapping": mapping, "votes": votes, "comptes": comptes}
    rapport["decision"] = {"gagnant": gagnant, "motif": motif}
    (out / "validation.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2))
    print(json.dumps(rapport["decision"], ensure_ascii=False))
    if args.enregistrer and gagnant:
        if not args.dataset_racine:
            print("--dataset-racine requis", file=sys.stderr)
            return 2
        entree = {"poids": args.lora, "config": {}, "etage": args.etage}
        entree["validation"] = rapport
        registre.enregistrer(args.dataset_racine, args.voix, entree)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
