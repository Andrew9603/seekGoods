from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


HARD_KEYS = {
    "hard_ban_categories",
    "daily_rest",
    "scheduled_rest_windows",
    "monthly_off_days",
    "max_pickup_deadhead_km",
    "max_haul_km",
    "required_region_order_days",
    "forbidden_regions",
    "required_location_stops",
    "home_rules",
    "allowed_regions",
    "unknown_hard_constraints",
    "requires_conservative_mode",
}


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
                if limit and len(rows) >= limit:
                    break
    return rows


def normalize(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        values = [normalize(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return value


def atoms(data: dict[str, Any], keys: set[str] | None = None) -> set[str]:
    result = set()
    for key, value in data.items():
        if keys is not None and key not in keys:
            continue
        normalized = normalize(value)
        if isinstance(normalized, list):
            if not normalized:
                result.add(f"{key}=<empty>")
            else:
                for item in normalized:
                    result.add(f"{key}={json.dumps(item, ensure_ascii=False, sort_keys=True)}")
        else:
            result.add(f"{key}={json.dumps(normalized, ensure_ascii=False, sort_keys=True)}")
    return result


def extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else None
        except Exception:
            return None
    return None


def render_prompt(tokenizer, messages: list[dict[str, str]]) -> str:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.adapter, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    base = AutoModelForCausalLM.from_pretrained(
        args.model,
        local_files_only=True,
        quantization_config=quantization_config,
        device_map={"": 0},
        dtype=torch.bfloat16,
    )
    model = PeftModel.from_pretrained(base, args.adapter, local_files_only=True)
    model.eval()

    rows = read_jsonl(args.data_file, args.limit)
    predictions = []
    tp = fp = fn = 0
    hard_tp = hard_fn = 0
    valid = exact = 0
    field_correct: dict[str, int] = {}
    challenge_unknown_correct = challenge_conservative_correct = 0
    challenge_count = 0

    for offset in range(0, len(rows), args.batch_size):
        batch = rows[offset : offset + args.batch_size]
        prompts = [render_prompt(tokenizer, row["messages"][:2]) for row in batch]
        encoded = tokenizer(prompts, return_tensors="pt", padding=True).to(model.device)
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        prompt_width = encoded["input_ids"].shape[1]
        outputs = tokenizer.batch_decode(generated[:, prompt_width:], skip_special_tokens=True)
        for row, raw in zip(batch, outputs):
            gold = normalize(row["constraints"])
            parsed = extract_json(raw)
            pred = normalize(parsed) if parsed is not None else {}
            valid += int(parsed is not None)
            exact += int(parsed is not None and pred == gold)
            gold_atoms, pred_atoms = atoms(gold), atoms(pred)
            tp += len(gold_atoms & pred_atoms)
            fp += len(pred_atoms - gold_atoms)
            fn += len(gold_atoms - pred_atoms)
            gold_hard, pred_hard = atoms(gold, HARD_KEYS), atoms(pred, HARD_KEYS)
            hard_tp += len(gold_hard & pred_hard)
            hard_fn += len(gold_hard - pred_hard)
            for key, value in gold.items():
                field_correct[key] = field_correct.get(key, 0) + int(pred.get(key) == value)
            if row["metadata"].get("split") == "challenge":
                challenge_count += 1
                challenge_unknown_correct += int(
                    pred.get("unknown_hard_constraints") == gold.get("unknown_hard_constraints")
                )
                challenge_conservative_correct += int(
                    pred.get("requires_conservative_mode") is True
                )
            predictions.append({
                "id": row["id"],
                "text": row["text"],
                "gold": gold,
                "prediction": parsed,
                "raw_output": raw,
            })
        print(f"evaluated {min(offset + len(batch), len(rows))}/{len(rows)}", flush=True)

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    metrics = {
        "samples": len(rows),
        "json_valid_rate": valid / max(1, len(rows)),
        "exact_match_rate": exact / max(1, len(rows)),
        "field_micro_precision": precision,
        "field_micro_recall": recall,
        "field_micro_f1": 2 * precision * recall / max(1e-12, precision + recall),
        "hard_constraint_recall": hard_tp / max(1, hard_tp + hard_fn),
        "field_exact_accuracy": {
            key: count / max(1, len(rows)) for key, count in sorted(field_correct.items())
        },
    }
    if challenge_count:
        metrics["unknown_hard_exact_rate"] = challenge_unknown_correct / challenge_count
        metrics["conservative_mode_recall"] = challenge_conservative_correct / challenge_count
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("w", encoding="utf-8") as handle:
        for item in predictions:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    metrics_path = args.output_file.with_suffix(".metrics.json")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
