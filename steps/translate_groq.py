#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Groq API based Spanish → Turkish subtitle translator.
Much faster and higher quality than local 1.3B NLLB.

Usage is identical to translate_srt_fast / translate_srt:
    translate_srt(es_srt, tr_srt, config, progress_cb=...)
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import List, Optional, Callable

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

from config import Config
from srt_parser import parse_srt, serialize_srt

log = logging.getLogger(__name__)

# Good fast models on Groq (as of 2026):
# - llama-3.3-70b-versatile   (excellent quality + speed for translation)
# - llama-3.1-70b-versatile
# - mixtral-8x7b-32768 (if needed)

DEFAULT_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"
LINES_PER_REQUEST = 15
MAX_RETRIES = 4


class GroqTranslationError(RuntimeError):
    pass


def is_srt_untranslated(
    source_path: Path,
    target_path: Path,
    *,
    threshold: float = 0.85,
) -> bool:
    """tr.srt dosyası es.srt ile neredeyse aynıysa çevrilmemiş say."""
    if not target_path.is_file() or target_path.stat().st_size == 0:
        return True
    if not source_path.is_file():
        return False

    src = parse_srt(source_path.read_text(encoding="utf-8"))
    dst = parse_srt(target_path.read_text(encoding="utf-8"))
    if not src or not dst:
        return True

    n = min(len(src), len(dst))
    if n == 0:
        return True

    same = sum(
        1 for i in range(n) if src[i].text.strip() == dst[i].text.strip()
    )
    return (same / n) >= threshold


def _get_client(api_key: str) -> "Groq":
    if Groq is None:
        raise RuntimeError("groq paketi yüklü değil. Lütfen: pip install groq")
    return Groq(api_key=api_key)


def _build_batch_prompt(
    lines: List[str],
    history: List[str],
    *,
    source_lang: str,
) -> str:
    """
    Build a strong prompt for batch translation.
    We send multiple lines at once for maximum speed.
    """
    history_block = ""
    if history:
        history_block = (
            "Previous Turkish translations (for style and recurring names/characters consistency - do NOT copy these literally for new lines):\n"
            + "\n".join(f"- {h}" for h in history[-3:])
            + "\n\n"
        )

    lines_block = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))

    if source_lang == "en":
        pair = "English → natural Turkish"
        input_label = "English"
        short_examples = '"What?", "What happened?", "Yes", "No" etc. give contextually appropriate Turkish'
    else:
        pair = "Spanish → natural Turkish TV subtitles (telenovela style)"
        input_label = "Spanish"
        short_examples = '"¿Qué?", "¿Qué pasa?", "Sí", "No" etc. give contextually appropriate Turkish'

    prompt = f"""You are an expert translator for {pair}.

CRITICAL RULES:
- Produce EXACTLY one Turkish translation per {input_label} input line.
- Vary your translations. Never output the exact same phrase for different input lines.
- For short lines like {short_examples} ("Ne?", "Ne oldu?", "Evet.", "Hayır." etc). Do not default everything to one phrase.
- Keep the dramatic tone, length and natural spoken Turkish.
- Names and terms must stay consistent with previous translations.
- Output ONLY valid JSON. No markdown, no extra text.

{history_block}Input {input_label} subtitle lines:
{lines_block}

Output format (MUST be valid JSON):
{{"translations": ["Türkçe 1", "Türkçe 2", "..."] }}
"""
    return prompt


def _parse_translations(raw: str, expected_count: int) -> List[str]:
    """Robustly parse model output into list of translations. Returns best-effort list of exact length."""
    text = raw.strip()

    # Try JSON (preferred: {"translations": [...]} or bare list)
    try:
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        data = json.loads(text)

        # Sometimes the value is still a JSON string
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict):
            for key in ("translations", "lines", "result", "output"):
                if key in data and isinstance(data[key], (list, str)):
                    data = data[key]
                    break

        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, list):
            cleaned = []
            for x in data:
                s = str(x).strip().strip('"\'').strip()
                if " - " in s and s.count("?") + s.count("!") > 1:  # merged lines
                    parts = re.split(r'\s*[-–/]\s*', s)
                    cleaned.extend([p.strip() for p in parts if p.strip()])
                else:
                    cleaned.append(s)
            if len(cleaned) >= expected_count:
                return cleaned[:expected_count]
    except Exception:
        pass

    # Fallbacks (more defensive)
    translations: List[str] = []

    # Numbered lines
    numbered = re.findall(r"^\s*\d+[\.\)]\s*(.+?)\s*$", text, re.MULTILINE)
    if len(numbered) >= expected_count:
        translations = [t.strip().strip('"\'') for t in numbered[:expected_count]]

    if not translations:
        # Try to extract quoted strings
        quoted = re.findall(r'"([^"]+)"', text)
        if len(quoted) >= expected_count:
            translations = [q.strip() for q in quoted[:expected_count]]

    if not translations:
        candidates = [ln.strip().strip('"\'') for ln in text.splitlines() if ln.strip()]
        candidates = [c for c in candidates 
                      if len(c) > 0 
                      and not c.lower().startswith(("note", "çeviri", "translation", "json", "output", "here"))]
        if candidates:
            translations = candidates[:expected_count]

    # Final safety pad using empty (caller will decide fallback)
    while len(translations) < expected_count:
        translations.append("")

    return translations[:expected_count]


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg


def _translate_batch_groq(
    client: Groq,
    lines: List[str],
    model: str,
    history_tr: List[str],
    *,
    fallback_model: str | None = None,
    source_lang: str = "es",
) -> List[str]:
    """Call Groq for a batch of lines."""
    if not lines:
        return []

    prompt = _build_batch_prompt(lines, history_tr, source_lang=source_lang)
    models_to_try = [model]
    if fallback_model and fallback_model not in models_to_try:
        models_to_try.append(fallback_model)

    last_error: Exception | None = None

    for current_model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=current_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a precise subtitle translator. "
                                "Always return clean valid JSON with the exact number of translations requested."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=3000,
                    top_p=0.9,
                )
                content = resp.choices[0].message.content or ""
                result = _parse_translations(content, len(lines))

                if len(result) != len(lines):
                    raise GroqTranslationError(
                        f"Model çıktısı satır sayısı uyuşmuyor ({len(result)} != {len(lines)})"
                    )

                unchanged = sum(
                    1 for src, dst in zip(lines, result) if src.strip() == dst.strip()
                )
                if len(lines) >= 3 and unchanged == len(lines):
                    raise GroqTranslationError(
                        "Model hiçbir satırı çevirmedi (çıktı kaynakla aynı)"
                    )

                non_empty = [r.strip() for r in result if r.strip()]
                unique = set(non_empty)
                if len(non_empty) > 4 and len(unique) <= 2:
                    short_repeated = all(len(u) < 20 for u in unique)
                    if short_repeated:
                        raise GroqTranslationError(
                            f"Model tekrarlayan kısa çıktı üretti: {unique}"
                        )

                cleaned = []
                for i, r in enumerate(result):
                    r = r.strip().strip('"\'').strip()
                    if r.count(" - ") >= 1 or r.count(" / ") >= 1:
                        parts = re.split(r"\s*[-/]\s*", r)
                        if len(parts) >= 2:
                            r = parts[0].strip() or lines[i]
                    cleaned.append(r if r else lines[i])

                result = cleaned[: len(lines)]

                good_for_history = [
                    r for r in result if len(r) > 3 and r not in ("Ne oldu?", "Ne?", "Evet.", "Hayır.")
                ]
                history_tr.extend(good_for_history)
                if len(history_tr) > 6:
                    history_tr[:] = history_tr[-6:]

                return result
            except GroqTranslationError:
                raise
            except Exception as e:
                last_error = e
                log.warning(f"[GROQ] {current_model} attempt {attempt + 1} failed: {e}")
                if _is_rate_limit_error(e) and current_model != models_to_try[-1]:
                    break
                time.sleep(1.0 * (attempt + 1))

    raise GroqTranslationError(
        f"Groq çeviri başarısız (son hata: {last_error}). "
        "API limiti dolmuş olabilir — bir süre bekleyip tekrar deneyin."
    ) from last_error


def translate_srt(
    input_path: Path,
    output_path: Path,
    config: Config,
    progress_cb: Optional[Callable[[float, int, int], None]] = None,
    *,
    force: bool = False,
    source_lang: str | None = None,
) -> Path:
    """
    Drop-in replacement using Groq API (very fast + high quality).
    Same signature as local translate_srt.
    """
    if (
        not force
        and output_path.exists()
        and output_path.stat().st_size > 0
        and not is_srt_untranslated(input_path, output_path)
    ):
        return output_path

    if not config.groq_api_key:
        raise RuntimeError("GROQ_API_KEY bulunamadı (config veya ortam değişkeni).")

    content = input_path.read_text(encoding="utf-8")
    entries = parse_srt(content)
    if not entries:
        raise RuntimeError(f"SRT boş veya okunamadı: {input_path}")

    texts = [e.text for e in entries]
    total = len(texts)
    if total == 0:
        return output_path

    lang = (source_lang or config.source_lang or "es").strip().lower()
    if lang not in ("es", "en"):
        lang = "es"

    client = _get_client(config.groq_api_key)
    model = config.groq_model or DEFAULT_MODEL
    fallback = getattr(config, "groq_fallback_model", None) or FALLBACK_MODEL
    batch_size = min(config.groq_lines_per_call or LINES_PER_REQUEST, 40)

    log.info(f"[GROQ] {total} satır çevriliyor | model={model} | batch≈{batch_size}")

    translated: List[str] = []
    history_tr: List[str] = []
    t0 = time.perf_counter()

    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        batch_out = _translate_batch_groq(
            client,
            batch,
            model,
            history_tr,
            fallback_model=fallback,
            source_lang=lang,
        )
        translated.extend(batch_out)

        done = min(start + len(batch), total)
        if progress_cb:
            try:
                progress_cb(done / total, done, total)
            except Exception:
                pass

        time.sleep(0.08)

    elapsed = time.perf_counter() - t0
    rate = total / max(elapsed, 0.001)
    log.info(f"[GROQ] {total} satır çevrildi ({elapsed:.1f}s = {rate:.0f} satır/s)")

    while len(translated) < total:
        translated.append(texts[len(translated)])

    for i in range(len(translated)):
        if not translated[i] or len(translated[i]) < 2:
            translated[i] = texts[i]

    unchanged = sum(
        1 for src, dst in zip(texts, translated) if src.strip() == dst.strip()
    )
    if unchanged / max(total, 1) >= 0.85:
        raise GroqTranslationError(
            f"Çeviri tamamlanmadı: {unchanged}/{total} satır hâlâ İspanyolca. "
            "Groq API limiti dolmuş olabilir."
        )

    for entry, new_text in zip(entries, translated):
        entry.text = (new_text or "").strip() or entry.text

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_srt(entries), encoding="utf-8")
    return output_path
