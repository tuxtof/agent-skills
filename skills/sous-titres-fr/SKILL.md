---
name: sous-titres-fr
description: Crée des sous-titres français (.fr.srt) pour des films ou des séries stockés en local (mkv, mp4, avi…), généralement en anglais. Vérifie d'abord les sous-titres déjà intégrés ou présents à côté du fichier pour les réutiliser, et ne lance Whisper qu'en dernier recours, puis traduit en respectant les normes du sous-titrage français. À utiliser dès que l'utilisateur veut des sous-titres FR, une VOSTFR, traduire un .srt/.ass en français, sous-titrer un épisode, une saison ou un dossier de vidéos, même s'il ne dit pas « srt » ou « sous-titres » (ex. « je veux regarder ce film en VO avec du français en bas », « french subs for this show »).
---

# Sous-titres français pour films et séries

Objectif : produire `<nom de la vidéo>.fr.srt` à côté de chaque vidéo, pour que VLC, Plex, Jellyfin ou Infuse le chargent tout seuls, avec la meilleure qualité possible et le moins de calcul possible.

Pourquoi cet ordre : une piste de sous-titres déjà présente a été faite par des humains, avec des timecodes calibrés. La traduire donne un bien meilleur résultat qu'une transcription Whisper, qui prend aussi des minutes ou des heures et peut se tromper sur les noms et les répliques qui se chevauchent. Whisper n'est donc utilisé qu'en dernier recours.

Les scripts se trouvent dans `scripts/` (dossier de ce skill) : `probe.py` choisit la source, `srt_tools.py` traite le texte des sous-titres. Ils n'ont besoin que de Python 3 (sans bibliothèque externe) et de ffmpeg/ffprobe. Les extractions se font directement avec `ffmpeg`.

## 1. Inspecter

```bash
python3 scripts/probe.py "/chemin/Film.mkv"            # un fichier
python3 scripts/probe.py /chemin/Saison1/*.mkv          # plusieurs
```

Le JSON liste les pistes audio et de sous-titres (langue, codec, forced, SDH), les `.srt` déjà présents à côté, et `recommendation.strategy`. Suivre cette recommandation, sauf bonne raison (le dire alors à l'utilisateur) :

| strategy | Action |
|---|---|
| `done` | Un `.fr.srt` existe déjà. Le signaler et s'arrêter, sauf si l'utilisateur veut le refaire. |
| `extract_fr` | Extraire la piste FR vers `.fr.srt`, lancer `check`, terminé. |
| `extract_translate` | Extraire la piste (EN de préférence) puis aller à l'étape 3. |
| `external_translate` | Utiliser le `.srt` externe comme source, puis aller à l'étape 3. |
| `whisper` | Étape 2 (transcription), puis étape 3. |

Deux points à connaître :
- Une piste **forced** ne contient que les passages en langue étrangère (quelques dizaines de lignes). Elle ne sert jamais de source principale. probe l'écarte déjà, mais méfie-toi aussi d'une piste anglaise anormalement courte par rapport à la durée (moins de ~100 sous-titres pour un film de 1 h 30). À l'inverse, certaines releases marquent « forced » une piste complète : probe la réhabilite si elle a au moins la moitié des sous-titres de la plus longue piste (`forced_mislabeled: true`).
- Les pistes **image** (`hdmv_pgs_subtitle`, `dvd_subtitle`) ne s'extraient pas en texte sans OCR. On passe à Whisper et on le dit à l'utilisateur.

Travailler dans un dossier temporaire par vidéo (par ex. `$TMPDIR/sous-titres-fr/<nom>/`), jamais à côté de la vidéo. Seul le `.fr.srt` final y est écrit.

```bash
# <sub_index> = recommendation.source.sub_index donné par probe
ffmpeg -y -v error -i "Film.mkv" -map 0:s:<sub_index> -c:s srt "$W/source.srt"
python3 scripts/srt_tools.py clean "$W/source.srt" "$W/source.clean.srt"
```

`clean` retire les balises HTML/ASS, les annotations SDH (`[MUSIC]`, `(sighs)`, `JOHN:`), les paroles ♩ et les blocs vides, puis renumérote. Le lancer à chaque fois : sur une piste non-SDH, il ne fait que normaliser.

## 2. Transcrire avec Whisper (seulement si strategy = whisper)

```bash
# <index> = recommendation.source.index donné par probe (index global du flux audio)
ffmpeg -y -v error -i "Film.mkv" -map 0:<index> -vn -ac 1 -ar 16000 -c:a pcm_s16le "$W/audio.wav"

# Apple Silicon (recommandé, rapide, rien à installer grâce à uvx) :
uvx --python 3.12 --from mlx-whisper mlx_whisper "$W/audio.wav" \
    --model mlx-community/whisper-large-v3-turbo --language en \
    --word-timestamps True --output-format json --output-dir "$W" --verbose False
# Sinon, whisper OpenAI : whisper "$W/audio.wav" --model medium --language en \
#     --word_timestamps True --output_format json --output_dir "$W"

python3 scripts/srt_tools.py from-whisper "$W/audio.json" "$W/source.srt"
python3 scripts/srt_tools.py clean "$W/source.srt" "$W/source.clean.srt"
```

- Demander du **JSON avec horodatage par mot**, pas du SRT : les segments SRT bruts de Whisper durent souvent 10 s ou plus, ou sont coupés en pleine phrase. `from-whisper` les redécoupe en vrais sous-titres (fin de phrase, 2 × 42 car., 6 s max).
- Prendre la piste audio anglaise indiquée par probe (`recommendation.source.index`). Si la VO n'est pas l'anglais, adapter `--language`.
- Transcrire dans la langue d'origine puis traduire soi-même. `--task translate` de Whisper ne sait traduire que vers l'anglais.
- Avant de lancer, tester la commande : un `whisper` Homebrew peut être cassé (« bad interpreter » après une mise à jour de Python). Dans ce cas, utiliser la variante uvx. Pour un film entier, lancer en arrière-plan et prévenir l'utilisateur de la durée (large-v3-turbo sur M1 : quelques minutes par heure de vidéo, plus le téléchargement du modèle la première fois).
- Whisper produit parfois des hallucinations sur les silences et la musique (la même phrase répétée, « Thanks for watching »). Les retirer du `source.clean.srt` **avant** `split` (supprimer le bloc puis relancer `clean` pour renuméroter) et le signaler.

## 3. Traduire en français

Lire d'abord `references/regles-sous-titrage-fr.md` (longueur des lignes, typographie, tu/vous, dialogues).

```bash
python3 scripts/srt_tools.py split "$W/source.clean.srt" "$W/chunks" --size 100
```

Pour chaque `chunk_NNN.txt`, écrire `chunk_NNN.fr.txt` dans le même format :
- Garder chaque marqueur `[N]` exactement, dans le même ordre, sans en ajouter ni en supprimer. Les timecodes sont réassociés par numéro au moment du merge, donc un marqueur perdu fait échouer l'assemblage.
- Une ou deux lignes de texte français sous chaque marqueur, jamais vide.
- Traduire le sens et adapter, sans calquer : condenser pour respecter environ 42 caractères par ligne et une vitesse de lecture confortable.
- Lire le chunk en entier avant de traduire : une phrase coupée sur deux sous-titres doit rester coupée au même endroit, sinon le texte ne correspond plus à l'image.

**Glossaire** : avant le premier chunk, créer `$W/glossaire.md` (pour une série, utiliser le glossaire persistant, voir plus bas) avec les noms des personnages, les lieux, les termes récurrents et le tu/vous entre les personnages. Le compléter au fil de la traduction et le relire avant chaque chunk : c'est ce qui garde la cohérence sur 1 000 sous-titres et plusieurs épisodes.

Pour un film long, on peut confier des chunks à des sous-agents en parallèle, en leur donnant le glossaire, les règles et les 5 derniers sous-titres du chunk précédent comme contexte.

```bash
python3 scripts/srt_tools.py merge "$W/source.clean.srt" "$W/chunks" "$W/final.fr.srt"
```

## 4. Contrôler et livrer

```bash
python3 scripts/srt_tools.py check "$W/final.fr.srt" --ref "$W/source.clean.srt"
```

- **ERREUR** (nombre de sous-titres ou timecodes différents) : corriger les chunks fautifs et relancer merge. Ne pas livrer en l'état.
- **ATTENTION** : corriger les lignes trop longues, les vitesses de lecture excessives, les espaces manquantes avant `? ! :` et les sous-titres non traduits. Seuls 60 avertissements s'affichent : ajouter `--all` pour la liste complète. Avec `--ref`, la vitesse n'est signalée que si le français est plus long que la VO ou dépasse 25 car./s : les séries au débit rapide ont souvent une VO déjà au-dessus de 20 car./s, et il est inutile de mutiler le sens pour passer sous ce seuil. Viser alors « pas plus long que la VO ». Les avertissements restants sur des sous-titres de moins d'une seconde sont acceptables.

Copier ensuite le résultat à côté de la vidéo : `cp "$W/final.fr.srt" "/chemin/Film.fr.srt"` (même nom de base que la vidéo). Si un `.fr.srt` existe déjà, demander avant d'écraser.

Incrustation dans le mkv : seulement si l'utilisateur le demande, en remuxant dans un **nouveau** fichier sans réencoder :
```bash
ffmpeg -i Film.mkv -i Film.fr.srt -map 0 -map 1 -c copy \
  -metadata:s:s:<n> language=fre -metadata:s:s:<n> title="Français" Film.fr.mkv
```
(`<n>` = nombre de pistes de sous-titres existantes.)

## Séries / dossiers

1. Lancer `probe.py` sur tous les épisodes d'un coup et présenter un résumé (épisode → stratégie). Annoncer à l'avance ceux qui demandent Whisper, c'est la partie longue.
2. **Glossaire commun persistant** : `~/.local/share/sous-titres-fr/<Série.Année>/glossaire.md`. S'il existe déjà (épisodes traités lors d'une session précédente), le reprendre tel quel : c'est ce qui garde les mêmes noms et le même tu/vous quand l'épisode suivant sort une semaine plus tard. Sinon, le créer avant de traduire, à partir des noms récurrents de la VO (`grep -oE '\b[A-Z][a-z]{2,}\b' | sort | uniq -c | sort -rn`) et d'une recherche rapide sur la série (page Wikipédia : personnages, relations, résumés d'épisodes). Les relations entre personnages décident du tu/vous : il vaut mieux les connaître avant la première ligne.
3. Traiter et contrôler chaque épisode comme un film. Des sous-agents peuvent prendre un épisode chacun, en parallèle. Leur donner : le chemin du glossaire, les règles, un résumé de l'épisode, et la consigne de **ne créer de fichiers (scripts d'aide compris) que dans leur dossier d'épisode**. Sinon, deux agents qui écrivent un `fix.py` au même endroit s'écrasent mutuellement. Chacun note ses ajouts dans `<épisode>/glossaire-ajouts.md` plutôt que d'éditer le glossaire partagé en même temps que les autres. Fusionner ces ajouts dans le glossaire persistant à la fin.
4. Avant de livrer, relire un échantillon de chaque épisode (début, milieu, fin, VO en regard) et vérifier la cohérence des noms et surnoms entre épisodes. Un surnom mal compris dans un épisode (ex. un sobriquet pris pour un métier) se détecte en cherchant ses occurrences dans toutes les VO.
5. Ignorer les `.fr.srt` déjà présents (strategy `done`), sauf demande contraire.

## Résumé final à l'utilisateur

Pour chaque vidéo, indiquer : la source utilisée (piste intégrée n°x / srt externe / Whisper), le fichier produit, le nombre de sous-titres et les avertissements restants. Rester bref.
