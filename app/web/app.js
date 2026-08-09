/* VoiceBuilder — frontend (M7). Vanilla JS, aucune dépendance. */
"use strict";

const $ = (id) => document.getElementById(id);

let voixNoms = [];
let docCourant = null;   // {fichier, brouillon}
let cm = null;           // instance CodeMirror

// ---------------------------------------------------------------- éditeur

// initialise l'éditeur CodeMirror (surlignage du texte taggé, numéros de ligne)
function initEditeur() {
  cm = CodeMirror($("zone-editeur"), {
    mode: "tagged",
    lineNumbers: true,
    lineWrapping: true,
    placeholder: "[Narrateur]: …",
    extraKeys: { Tab: completer },
  });
  cm.on("change", () => autoEnregistrer());
}

// ---------------------------------------------------------------- autocomplétion (Tab)
function completer() {
  const { line, ch } = cm.getCursor();
  const ligne = cm.getLine(line).slice(0, ch);
  const idx = ligne.lastIndexOf("[");
  if (idx < 0 || ligne.indexOf("]", idx) < ch) return;
  const prefixe = ligne.slice(idx + 1).toLowerCase();
  const nom = voixNoms.map((v) => v.nom)
    .find((n) => n.toLowerCase().startsWith(prefixe));
  if (nom) {
    cm.replaceRange(nom.slice(prefixe.length),
      { line, ch }, { line, ch });
    cm.focus();
  }
}

// ---------------------------------------------------------------- autosave
function autoEnregistrer() {
  if (!docCourant) return;
  clearTimeout(autoEnregistrer._t);
  autoEnregistrer._t = setTimeout(async () => {
    try {
      await fetch("/api/document/enregistrer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fichier: docCourant.fichier, contenu: cm.getValue() }),
      });
      $("doc-statut").textContent = "✔ sauvegardé";
    } catch { $("doc-statut").textContent = "⚠ échec sauvegarde"; }
  }, 600);
}

// ---------------------------------------------------------------- documents
async function chargerDocuments() {
  const r = await fetch("/api/documents");
  const { documents } = await r.json();
  const sel = $("sel-doc");
  sel.innerHTML = "";
  for (const d of documents) {
    const o = document.createElement("option");
    o.value = d; o.textContent = d;
    sel.appendChild(o);
  }
}
$("btn-ouvrir").addEventListener("click", async () => {
  const choix = $("sel-doc").value;
  if (!choix) return;
  const r = await fetch("/api/document/ouvrir", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fichier: choix }),
  });
  const d = await r.json();
  docCourant = { fichier: d.fichier, brouillon: d.brouillon };
  cm.setValue(d.contenu ?? "");
  cm.refresh();
  $("doc-statut").textContent =
    `brouillon : ${d.brouillon} (fichier source non modifié)`;
});

// ---------------------------------------------------------------- voix
async function chargerEtat() {
  const etat = await (await fetch("/api/etat")).json();
  $("audio-dir").value = etat.audio_dir;
  $("n-voix").textContent = etat.voix.length || 0;
  if (!etat.voix_file && etat.erreur) {
    afficherBanniere(etat.erreur, true);
  } else if (!etat.voix_file) {
    afficherBanniere("Aucun fichier de voix : configure le dossier des voix.", true);
  } else {
    masquerBanniere();
  }
}

async function chargerVoix() {
  const r = await fetch("/api/voix");
  if (!r.ok) { voixNoms = []; return; }
  voixNoms = await r.json();
  const ul = $("liste-voix");
  ul.innerHTML = "";
  voixNoms.forEach((v, i) => {
    const li = document.createElement("li");
    li.textContent = v.nom;
    li.onclick = () => {
      ul.querySelectorAll("li").forEach((x) => x.classList.remove("sel"));
      li.classList.add("sel");
    };
    const ecoute = document.createElement("button");
    ecoute.textContent = "▶";
    ecoute.title = "pré-écoute";
    ecoute.onclick = (e) => {
      e.stopPropagation();
      const a = new Audio(`/api/voix/wav?nom=${encodeURIComponent(v.nom)}`);
      a.play();
    };
    li.appendChild(ecoute);
    ul.appendChild(li);
  });
  $("n-voix").textContent = voixNoms.length;
}

$("inserer").addEventListener("click", () => {
  const sel = document.querySelector("#liste-voix li.sel");
  if (!sel) { alert("Sélectionne une voix."); return; }
  const nom = sel.textContent.replace("▶", "").trim();
  let t = cm.getValue();
  if (t && !t.endsWith("\n")) t += "\n";
  cm.setValue(t + `[${nom}]: `);
  cm.focus();
});

// ---------------------------------------------------------------- réglages
$("btn-dir").addEventListener("click", async () => {
  const r = await fetch("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_dir: $("audio-dir").value }),
  });
  if (!r.ok) { alert((await r.json()).detail); return; }
  chargerVoix();
  chargerEtat();
});
$("btn-save").addEventListener("click", () =>
  alert("Réglages utilisés côté serveur à la génération."));

// ---------------------------------------------------------------- génération
$("generer").addEventListener("click", async () => {
  $("log").textContent = "Lancement…\n";
  $("montage").src = "";
  const r = await fetch("/api/generer", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texte: cm.getValue(),
      pause: parseFloat($("pause").value),
      vitesse: parseFloat($("vitesse").value),
      max_chars: parseInt($("maxchars").value, 10),
      verify: $("verify").checked,
      device: $("device").value,
    }),
  });
  if (!r.ok) { $("log").textContent += (await r.json()).detail; return; }
  const { id } = await r.json();

  const ev = new EventSource(`/api/generer/${id}/stream`);
  ev.addEventListener("bloc", (e) => {
    const b = JSON.parse(e.data);
    $("log").textContent +=
      `[${b.index}/${b.total}] ${b.personnage} (${b.chars} chars) — ${b.duree} s\n`;
  });
  ev.addEventListener("result", (e) => {
    const res = JSON.parse(e.data);
    $("log").textContent +=
      `\nTerminé : ${res.duree} s, ${res.blocs.length} blocs.\n`;
    $("montage").src = `/api/generer/${id}/result`;
  });
  ev.addEventListener("error", (e) => {
    const d = JSON.parse(e.data).error;
    $("log").textContent += `\n❌ ${d}\n`;
  });
  ev.addEventListener("end", () => ev.close());
});

// ---------------------------------------------------------------- bannière
function afficherBanniere(msg, avecLien) {
  $("banniere-msg").textContent = msg;
  $("banniere-lien").hidden = !avecLien;
  $("banniere").hidden = false;
}
function masquerBanniere() { $("banniere").hidden = true; }
$("banniere-lien").addEventListener("click", (e) => {
  e.preventDefault();
  $("reglages").scrollIntoView({ behavior: "smooth" });
});

// ---------------------------------------------------------------- init
(async function init() {
  initEditeur();
  await chargerDocuments();
  await chargerEtat();
  await chargerVoix();
})();