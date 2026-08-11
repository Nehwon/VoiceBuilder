# Démo — VoiceBuilder (M2.3)

Validation de bout en bout du pipeline (M0/M1) avec un échantillon de test.

## Contenu du dossier

- `../texte/exemple_demo.md` — un texte taggé multi-personnages (prose non
  attribuée = locuteur précédent, plusieurs voix distinctes).
- `../voix/voix.txt` — les voix (couples `.wav` + `.txt`) du dossier
  `VOICEBUILDER_AUDIO_DIR` (défaut `~/Partages/voice`).

## Test de bout en bout (parse → blocs → voix)

```bash
# 1. Vérification du découpage (sans générer d'audio)
#    (à exécuter depuis la racine du projet)
~/VoiceBuilder/vendor/CosyVoice/venv/bin/python - <<'PY'
import sys
sys.path.insert(0, '.')
from pathlib import Path
from engine.config import PROJECT_ROOT
from engine.voix import load_voix
from engine.tagging import parse_texte, regrouper
text = (PROJECT_ROOT/'texte'/'exemple_demo.md').read_text()
for pers, bloc in regrouper(parse_texte(text, load_voix().names())):
    print(f'[{pers}] ({len(bloc)} chars): {bloc[:50]!r}')
PY

# 2. Génération complète d'un montage
~/VoiceBuilder/vendor/CosyVoice/venv/bin/python -m tools.gen_multi_voix texte/exemple_demo.md \
    -o output/exemple_demo.wav --vitesse 1.0 --pause 0.45
```

## Assistant de création de voix (M2.1 / M2.2)

```bash
# Extraire + transcrire un segment (langue, alerte longueur)
python -m tools.create_voix SOURCE.wav --nom LeNarrateur \
    --start 0 --stop 25 --lang fr --max-sec 30

# Avec sortie horodatée par segment
python -m tools.create_voix SOURCE.wav --nom LeNarrateur \
    --start 0 --stop 25 --timestamps
```