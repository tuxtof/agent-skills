#!/usr/bin/env python3
"""Inspecte une vidéo et recommande la meilleure source pour des sous-titres FR.

Usage: probe.py <video> [<video> ...]
Sortie: JSON (une entrée par vidéo) avec les pistes audio/sous-titres,
les .srt externes déjà présents et une recommandation `strategy`:
  - "done"          : un .fr.srt existe déjà à côté de la vidéo
  - "extract_fr"    : piste FR texte intégrée -> extraire, pas de traduction
  - "extract_translate" : piste texte (EN de préférence) -> extraire puis traduire
  - "external_translate": .srt externe (EN) à côté de la vidéo -> traduire
  - "whisper"       : rien d'exploitable -> transcrire l'audio puis traduire
"""
import json
import subprocess
import sys
from pathlib import Path

TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
FR = {"fre", "fra", "fr"}
EN = {"eng", "en"}


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe a échoué")
    return json.loads(out.stdout)


def stream_info(s: dict, sub_index: int | None = None) -> dict:
    tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
    disp = s.get("disposition") or {}
    title = tags.get("title", "")
    tl = title.lower()
    info = {
        "index": s["index"],
        "codec": s.get("codec_name"),
        "language": (tags.get("language") or "und").lower(),
        "title": title,
        "default": bool(disp.get("default")),
        "forced": bool(disp.get("forced")) or "forced" in tl or "forcé" in tl,
        "sdh": bool(disp.get("hearing_impaired")) or "sdh" in tl or "cc" == tl.strip(),
    }
    if sub_index is not None:
        info["sub_index"] = sub_index  # à utiliser avec -map 0:s:<sub_index>
        info["kind"] = ("text" if info["codec"] in TEXT_CODECS
                        else "image" if info["codec"] in IMAGE_CODECS else "unknown")
        n = tags.get("number_of_frames") or tags.get("number_of_frames-eng")
        if n:
            info["events"] = int(n)
    if s.get("codec_type") == "audio":
        info["channels"] = s.get("channels")
    return info


def external_subs(video: Path) -> list[dict]:
    res = []
    for p in sorted(video.parent.glob(video.stem + "*.srt")):
        suffix = p.name[len(video.stem):-len(".srt")].lower().strip(".")
        parts = set(suffix.split(".")) if suffix else set()
        lang = "fr" if parts & (FR | {"french", "francais"}) else \
               "en" if parts & (EN | {"english"}) else "und"
        res.append({"path": str(p), "language": lang,
                    "forced": "forced" in parts, "sdh": bool(parts & {"sdh", "cc", "hi"})})
    return res


def rank(sub: dict) -> tuple:
    # plus petit = meilleur : non forcé, non SDH, plus d'événements
    return (sub["forced"], sub["sdh"], -(sub.get("events") or 0))


def recommend(subs: list[dict], ext: list[dict], audio: list[dict]) -> dict:
    for e in ext:
        if e["language"] == "fr" and not e["forced"]:
            return {"strategy": "done", "source": e,
                    "reason": "Un .srt français existe déjà à côté de la vidéo."}
    text = [s for s in subs if s["kind"] == "text"]
    fr = sorted([s for s in text if s["language"] in FR and not s["forced"]], key=rank)
    if fr:
        return {"strategy": "extract_fr", "source": fr[0],
                "reason": "Piste française texte intégrée : extraction directe."}
    en = sorted([s for s in text if s["language"] in EN and not s["forced"]], key=rank)
    if en:
        return {"strategy": "extract_translate", "source": en[0],
                "reason": "Piste anglaise texte intégrée : extraire puis traduire (pas de Whisper)."}
    ext_en = [e for e in ext if e["language"] in ("en", "und") and not e["forced"]]
    if ext_en:
        return {"strategy": "external_translate", "source": ext_en[0],
                "reason": "Sous-titre externe trouvé : le traduire."}
    other = sorted([s for s in text if not s["forced"]], key=rank)
    if other:
        return {"strategy": "extract_translate", "source": other[0],
                "reason": f"Piste texte en '{other[0]['language']}' : extraire puis traduire."}
    images = [s for s in subs if s["kind"] == "image"]
    pick_audio = sorted(audio, key=lambda a: (a["language"] not in EN, not a["default"]))
    reason = "Aucun sous-titre texte exploitable : transcription Whisper."
    if images:
        reason += (" Des pistes image (PGS/VobSub) existent mais ne sont pas "
                   "convertibles en texte sans OCR.")
    return {"strategy": "whisper", "source": pick_audio[0] if pick_audio else None,
            "reason": reason}


def probe(path: Path) -> dict:
    data = ffprobe(path)
    streams = data.get("streams", [])
    subs, audio, si = [], [], 0
    for s in streams:
        if s.get("codec_type") == "subtitle":
            subs.append(stream_info(s, si)); si += 1
        elif s.get("codec_type") == "audio":
            audio.append(stream_info(s))
    # Un « forced » aussi long qu'une piste complète est un mauvais étiquetage (fréquent sur les releases)
    biggest = max((s.get("events") or 0 for s in subs), default=0)
    for s in subs:
        if s["forced"] and biggest and (s.get("events") or 0) >= 0.5 * biggest:
            s["forced"] = False
            s["forced_mislabeled"] = True
    ext = external_subs(path)
    return {
        "file": str(path),
        "duration_s": round(float(data.get("format", {}).get("duration") or 0), 1),
        "audio": audio,
        "subtitles": subs,
        "external_srt": ext,
        "recommendation": recommend(subs, ext, audio),
    }


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    results = []
    for arg in sys.argv[1:]:
        try:
            results.append(probe(Path(arg)))
        except Exception as e:  # noqa: BLE001
            results.append({"file": arg, "error": str(e)})
    print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
