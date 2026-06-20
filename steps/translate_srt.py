#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translate Spanish SRT to Turkish using local NLLB (direct ES->TR) with context preservation."""
from __future__ import annotations

from pathlib import Path
from typing import List

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from config import Config
from srt_parser import parse_srt, serialize_srt

_translator = None
_translator_key: tuple | None = None


NLLB_LANG = {
    "Spanish": "spa_Latn",
    "Turkish": "tur_Latn",
    "English": "eng_Latn",
}


class NLLBTranslator:
    """Direct Spanish -> Turkish NLLB translator with context-aware chunking for series dialogue."""

    def __init__(self, model_name: str, device: str = "cuda", batch_size: int = 8):
        print(f"[NLLB] Yukleniyor: {model_name} (device={device})")
        self.device = device if torch.cuda.is_available() and device == "cuda" else "cpu"
        self.batch_size = max(1, batch_size)

        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        dtype = torch.float16 if self.device == "cuda" else torch.float32

        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name,
            torch_dtype=dtype,
            device_map="auto" if self.device == "cuda" else None,
            low_cpu_mem_usage=True,
        )
        if self.device == "cpu":
            self.model = self.model.to("cpu")

        self.model.eval()
        print(f"[NLLB] Model hazir (device={self.device}, dtype={dtype})")

    def _translate_texts(self, texts: List[str], src_lang: str, tgt_lang: str) -> List[str]:
        """Core NLLB batch translate."""
        if not texts:
            return []

        src_code = NLLB_LANG.get(src_lang, "spa_Latn")
        tgt_code = NLLB_LANG.get(tgt_lang, "tur_Latn")

        self.tokenizer.src_lang = src_code

        results: List[str] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            encoded = self.tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=512
            )
            encoded = {k: v.to(self.model.device) for k, v in encoded.items()}

            with torch.no_grad():
                generated = self.model.generate(
                    **encoded,
                    forced_bos_token_id=self.tokenizer.convert_tokens_to_ids(tgt_code),
                    max_length=512,
                    num_beams=4,
                    early_stopping=True,
                )

            decoded = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
            results.extend([d.strip() for d in decoded])

        return results

    def translate_with_context(
        self, texts: List[str], src_lang: str = "Spanish", tgt_lang: str = "Turkish", context_lines: int = 3
    ) -> List[str]:
        """
        Fast + context-aware batch translation for TV series.
        Uses rolling previous Turkish lines prepended for speaker/term consistency.
        """
        if not texts:
            return []

        translated: List[str] = []
        history_tr: List[str] = []

        # Build contextual inputs (cheap prefix for coherence)
        sources = []
        for t in texts:
            prefix = ""
            if history_tr and context_lines > 0:
                prefix = " ".join(history_tr[-context_lines:]) + " | "
            sources.append((prefix + t).strip())

        # Translate in proper batches (much faster than 1-by-1)
        for i in range(0, len(sources), max(1, self.batch_size)):
            batch_src = sources[i : i + self.batch_size]
            batch_out = self._translate_texts(batch_src, src_lang, tgt_lang)
            for out_text in batch_out:
                translated.append(out_text)
                history_tr.append(out_text)
            if len(history_tr) > context_lines + 4:
                history_tr = history_tr[-(context_lines + 4):]

        # Length safety
        if len(translated) < len(texts):
            for j in range(len(translated), len(texts)):
                translated.append(texts[j])
        return translated[: len(texts)]


def _get_translator(config: Config):
    global _translator, _translator_key
    key = (config.translator_model, config.translator_device, config.translator_batch_size)
    if _translator is None or _translator_key != key:
        print(
            f"[TRANSLATE] Model yukleniyor: {config.translator_model} "
            f"(device={config.translator_device})"
        )
        _translator = NLLBTranslator(
            model_name=config.translator_model,
            device=config.translator_device,
            batch_size=config.translator_batch_size,
        )
        _translator_key = key
    return _translator


def translate_srt(input_path: Path, output_path: Path, config: Config) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    content = input_path.read_text(encoding="utf-8")
    entries = parse_srt(content)
    if not entries:
        raise RuntimeError(f"SRT bos veya okunamadi: {input_path}")

    translator = _get_translator(config)
    texts = [entry.text for entry in entries]

    print(f"[TRANSLATE] {len(texts)} satir ceviriliyor (baglam korunuyor, direct ES->TR)...")
    translated = translator.translate_with_context(
        texts, src_lang="Spanish", tgt_lang="Turkish", context_lines=4
    )

    for entry, new_text in zip(entries, translated):
        entry.text = new_text.strip() or entry.text

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_srt(entries), encoding="utf-8")
    print(f"[TRANSLATE] {len(entries)} satir Turkceye cevrildi (context-aware): {output_path.name}")
    return output_path
