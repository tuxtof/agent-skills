#!/usr/bin/env python3
"""Outils SRT pour la traduction par lots.

  srt_tools.py clean  <in.srt> <out.srt>            # retire balises, annotations SDH, blocs vides, renumérote
  srt_tools.py from-whisper <whisper.json> <out.srt> # resegmente un JSON Whisper (word timestamps) en vrais sous-titres
  srt_tools.py split  <in.srt> <dir> [--size 100]   # découpe en chunk_001.txt ... (format simplifié à traduire)
  srt_tools.py merge  <in.srt> <dir> <out.srt>      # réassemble les chunk_XXX.fr.txt avec les timecodes d'origine
  srt_tools.py check  <out.srt> [--ref in.srt] [--all]  # contrôle qualité (exit 1 si erreur bloquante)

Format des chunks (à traduire ligne à ligne, sans toucher aux marqueurs) :
  [12]
  texte ligne 1
  texte ligne 2

Les timecodes ne sont jamais exposés au traducteur : merge les reprend du SRT source.
"""
import re
import sys
from pathlib import Path

TC = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
MARK = re.compile(r"^\[(\d+)\]\s*$")


def to_ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0"))


def fmt(ms: int) -> str:
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def parse(path: str) -> list[dict]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines[:3]):
            m = TC.search(line)
            if m:
                g = m.groups()
                cues.append({"start": to_ms(*g[:4]), "end": to_ms(*g[4:]),
                             "lines": [l for l in lines[i + 1:] if l.strip()]})
                break
    return cues


def write(cues: list[dict], path: str) -> None:
    out = []
    for n, c in enumerate(cues, 1):
        out.append(f"{n}\n{fmt(c['start'])} --> {fmt(c['end'])}\n" + "\n".join(c["lines"]))
    Path(path).write_text("\n\n".join(out) + "\n", encoding="utf-8")


SDH = [
    re.compile(r"\[[^\]]*\]"),            # [MUSIC], [door slams]
    re.compile(r"\([^)]*\)"),             # (sighs)
    re.compile(r"[♪♫#]+.*?[♪♫#]*$"),      # paroles de chanson
]
SPEAKER = re.compile(r"^(-\s*)?[A-Z][A-Z0-9 .'-]{1,25}:\s*")  # JOHN: Hello
TAGS = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def clean(cues: list[dict]) -> list[dict]:
    res = []
    for c in cues:
        lines = []
        for l in c["lines"]:
            l = TAGS.sub("", l)
            for p in SDH:
                l = p.sub("", l)
            l = SPEAKER.sub(lambda m: m.group(1) or "", l)
            l = re.sub(r"\s{2,}", " ", l).strip()
            if l and l not in {"-", "–", "—"}:
                lines.append(l)
        if lines:
            res.append({**c, "lines": lines})
    return res


def wrap2(text: str, width: int = 42) -> list[str]:
    if len(text) <= width:
        return [text]
    words, best = text.split(), None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(a), len(b)) - (3 if a.endswith((",", ".", "?", "!")) else 0)
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1]


def from_whisper(json_path: str, out: str, max_chars: int = 84, max_ms: int = 6000) -> None:
    import json
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    words = [w for s in data.get("segments", []) for w in s.get("words", [])]
    if not words:
        sys.exit("Pas de timestamps par mot : relancer Whisper avec --word-timestamps True")
    cues, cur = [], []

    def flush():
        if cur:
            text = " ".join(w["word"].strip() for w in cur).strip()
            cues.append({"start": int(cur[0]["start"] * 1000), "end": int(cur[-1]["end"] * 1000),
                         "lines": wrap2(text)})
            cur.clear()

    for i, w in enumerate(words):
        if cur:
            text = " ".join(x["word"].strip() for x in cur + [w])
            gap = w["start"] - cur[-1]["end"]
            if len(text) > max_chars or (w["end"] - cur[0]["start"]) * 1000 > max_ms or gap > 1.0:
                # recule jusqu'à la dernière ponctuation si possible
                cut = max((j for j, x in enumerate(cur) if x["word"].strip().endswith((".", "?", "!", ","))),
                          default=None)
                if cut is not None and cut < len(cur) - 1 and gap <= 1.0:
                    rest = cur[cut + 1:]
                    del cur[cut + 1:]
                    flush(); cur.extend(rest)
                else:
                    flush()
        cur.append(w)
        if w["word"].strip().endswith((".", "?", "!")) and len(" ".join(x["word"].strip() for x in cur)) > 30:
            flush()
    flush()
    for a, b in zip(cues, cues[1:]):
        a["end"] = min(max(a["end"], a["start"] + 1000), b["start"])  # durée min 1 s sans chevauchement
    write(cues, out)
    print(f"{len(cues)} sous-titres -> {out}")


def split(cues, outdir: str, size: int) -> None:
    d = Path(outdir)
    d.mkdir(parents=True, exist_ok=True)
    for k in range(0, len(cues), size):
        part = cues[k:k + size]
        body = "\n\n".join(f"[{k + i + 1}]\n" + "\n".join(c["lines"]) for i, c in enumerate(part))
        (d / f"chunk_{k // size + 1:03}.txt").write_text(body + "\n", encoding="utf-8")
    print(f"{len(cues)} sous-titres -> {(len(cues) + size - 1) // size} chunks dans {d}")


def read_chunks(outdir: str) -> dict[int, list[str]]:
    tr: dict[int, list[str]] = {}
    files = sorted(Path(outdir).glob("chunk_*.fr.txt"))
    if not files:
        sys.exit(f"Aucun chunk_*.fr.txt dans {outdir}")
    for f in files:
        cur = None
        for line in f.read_text(encoding="utf-8").split("\n"):
            m = MARK.match(line.strip())
            if m:
                cur = int(m.group(1)); tr[cur] = []
            elif cur is not None and line.strip():
                tr[cur].append(line.strip())
    return tr


def merge(cues, outdir: str, out: str) -> None:
    tr = read_chunks(outdir)
    missing = [i for i in range(1, len(cues) + 1) if not tr.get(i)]
    extra = [i for i in tr if i > len(cues)]
    if missing or extra:
        sys.exit(f"Merge impossible. Manquants: {missing[:30]} Inattendus: {extra[:30]}")
    write([{**c, "lines": tr[i]} for i, c in enumerate(cues, 1)], out)
    print(f"OK: {out} ({len(cues)} sous-titres)")


def check(path: str, ref: str | None, show_all: bool = False) -> None:
    cues = parse(path)
    rc = parse(ref) if ref else None
    aligned = rc is not None and len(rc) == len(cues)
    errors, warns = [], []
    if not cues:
        errors.append("Aucun sous-titre lisible.")
    for n, c in enumerate(cues, 1):
        dur = c["end"] - c["start"]
        text = " ".join(c["lines"])
        if dur <= 0:
            errors.append(f"#{n}: durée nulle/négative")
        if n > 1 and c["start"] < cues[n - 2]["end"] - 1:
            warns.append(f"#{n}: chevauche le précédent")
        if len(c["lines"]) > 2:
            warns.append(f"#{n}: {len(c['lines'])} lignes (max 2)")
        for l in c["lines"]:
            if len(l) > 42:
                warns.append(f"#{n}: ligne de {len(l)} car. (> 42)")
        if dur > 0:
            cps = len(text) / (dur / 1000)
            # Avec une référence, on ne signale que ce que la traduction a aggravé :
            # une source déjà très dense ne peut pas toujours descendre sous 20 car./s.
            src_len = len(" ".join(rc[n - 1]["lines"])) if aligned else 0
            if cps > 25 or (cps > 20 and (not aligned or len(text) > src_len)):
                warns.append(f"#{n}: {cps:.0f} car./s sur {dur / 1000:.1f} s — « {text} »"
                             + (f" (VO : {src_len} car.)" if aligned else ""))
        if re.search(r"[A-Za-z]\?|[A-Za-z]!|[A-Za-z]:(?!\d)", text):
            warns.append(f"#{n}: espace manquante avant ? ! ou :")
    if rc is not None:
        if not aligned:
            errors.append(f"Nombre de sous-titres différent: {len(cues)} vs {len(rc)} (ref)")
        else:
            for n, (a, b) in enumerate(zip(cues, rc), 1):
                if (a["start"], a["end"]) != (b["start"], b["end"]):
                    errors.append(f"#{n}: timecode modifié par rapport à la ref")
                    break
                # 3 mots ou plus : évite les faux positifs (« Morgan. », « Terrible. », titres)
                if a["lines"] == b["lines"] and len(re.findall(r"[A-Za-z']+", " ".join(a["lines"]))) >= 3:
                    warns.append(f"#{n}: identique à la source (non traduit ?)")
    print(f"{path}: {len(cues)} sous-titres, {len(errors)} erreur(s), {len(warns)} avertissement(s)")
    for e in errors:
        print("ERREUR  ", e)
    limit = len(warns) if show_all else 60
    for w in warns[:limit]:
        print("ATTENTION", w)
    if len(warns) > limit:
        print(f"... +{len(warns) - limit} avertissements (--all pour tout voir)")
    sys.exit(1 if errors else 0)


def main() -> None:
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "clean" and len(a) == 3:
        cues = clean(parse(a[1])); write(cues, a[2]); print(f"{len(cues)} sous-titres -> {a[2]}")
    elif cmd == "from-whisper" and len(a) == 3:
        from_whisper(a[1], a[2])
    elif cmd == "split" and len(a) >= 3:
        size = int(a[a.index("--size") + 1]) if "--size" in a else 100
        split(parse(a[1]), a[2], size)
    elif cmd == "merge" and len(a) == 4:
        merge(parse(a[1]), a[2], a[3])
    elif cmd == "check" and len(a) >= 2:
        check(a[1], a[a.index("--ref") + 1] if "--ref" in a else None, "--all" in a)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
