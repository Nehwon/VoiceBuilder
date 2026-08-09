# VoiceBuilder — règles de synchronisation

## Poussée vers les deux dépôts (par défaut)

- `origin` (gitea.lamachere.fr:2222) et le **backup GitHub**
  (`git@github.com:Nehwon/VoiceBuilder.git`, remote `backup`) sont tous deux
  maintenus à jour.
- Un simple `git push origin <branche>` pousse vers **les deux** (les deux
  `pushurl` sont configurés sur `origin`). On peut aussi pousser explicitement :
  `git push` + `git push backup`.
- **Par défaut, toute synchronisation pousse vers les deux dépôts**, sauf si
  l'utilisateur demande autre chose (ex. « pousse seulement sur gitea »).

## Règle de validation (ne change pas)

- Ne faire `git commit` / `git push` que lorsque l'utilisateur le demande
  explicitement. Toutes les modifications de fichiers sont libres, mais la
  validation et la publication restent suspendues à sa demande.