from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def render_prompt(tokenizer: Any, messages: list[dict[str, str]]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )


@torch.inference_mode()
def completion_logprob(model: Any, tokenizer: Any, prompt: str, completion: str, max_length: int) -> float:
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full = prompt + completion + tokenizer.eos_token
    encoded = tokenizer(
        full,
        add_special_tokens=False,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    input_ids = encoded["input_ids"].to(model.device)
    attention_mask = encoded["attention_mask"].to(model.device)
    prompt_len = min(len(prompt_ids), input_ids.shape[1] - 1)
    outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    logits = outputs.logits[:, :-1, :]
    labels = input_ids[:, 1:]
    log_probs = torch.log_softmax(logits, dim=-1)
    token_log_probs = log_probs.gather(-1, labels.unsqueeze(-1)).squeeze(-1)
    completion_scores = token_log_probs[:, prompt_len:]
    if completion_scores.numel() == 0:
        return float("-inf")
    return float(completion_scores.mean().detach().cpu())


def load_model(model_path: Path, adapter_path: Path):
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    base = AutoModelForCausalLM.from_pretrained(
        model_path,
        local_files_only=True,
        quantization_config=quantization_config,
        device_map="auto",
        dtype=torch.bfloat16,
    )
    model = PeftModel.from_pretrained(base, adapter_path)
    model.eval()
    return model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = load_model(args.model, args.adapter)

    rows = read_jsonl(args.data_file, args.limit)
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    correct = 0
    margins: list[float] = []
    type_counts: dict[str, int] = {}
    type_correct: dict[str, int] = {}
    with args.output_file.open("w", encoding="utf-8") as fh:
        for i, row in enumerate(rows, 1):
            prompt = render_prompt(tokenizer, row["messages"])
            chosen_score = completion_logprob(model, tokenizer, prompt, row["chosen"], args.max_length)
            rejected_score = completion_logprob(model, tokenizer, prompt, row["rejected"], args.max_length)
            ok = chosen_score > rejected_score
            correct += int(ok)
            margin = chosen_score - rejected_score
            margins.append(margin)
            pair_type = str(row.get("pair_type", "unknown"))
            type_counts[pair_type] = type_counts.get(pair_type, 0) + 1
            type_correct[pair_type] = type_correct.get(pair_type, 0) + int(ok)
            record = {
                "id": row.get("id"),
                "pair_type": pair_type,
                "chosen_score": chosen_score,
                "rejected_score": rejected_score,
                "margin": margin,
                "correct": ok,
                "metadata": row.get("metadata", {}),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            if i % 20 == 0:
                print(f"evaluated {i}/{len(rows)}", flush=True)

    metrics = {
        "samples": len(rows),
        "pairwise_accuracy": correct / max(len(rows), 1),
        "avg_margin": sum(margins) / max(len(margins), 1),
        "pair_type_accuracy": {
            key: type_correct.get(key, 0) / max(count, 1)
            for key, count in sorted(type_counts.items())
        },
    }
    args.output_file.with_suffix(".metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
