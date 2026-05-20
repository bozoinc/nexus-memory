#!/usr/bin/env python3
"""
NEXUS LongMemEval Evaluation Script v2
Uses a free model with higher token limits (Gemini 2.5 Flash)

Usage:
    python benchmarks/longmemeval/evaluate_nexus_v2.py results.jsonl data/longmemeval_oracle.json
"""

import os
import sys
import json
from pathlib import Path
from tqdm import tqdm
import backoff

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)


def get_anscheck_prompt(task, question, answer, response, abstention=False):
    """Same prompt template as LongMemEval's evaluate_qa.py"""
    if not abstention:
        if task in ['single-session-user', 'single-session-assistant', 'multi-session']:
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            return template.format(question, answer, response)
        elif task == 'temporal-reasoning':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            return template.format(question, answer, response)
        elif task == 'knowledge-update':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            return template.format(question, answer, response)
        elif task == 'single-session-preference':
            template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            return template.format(question, answer, response)
        else:
            raise NotImplementedError(f"Unknown task: {task}")
    else:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        return template.format(question, answer, response)


@backoff.on_exception(backoff.expo, Exception, max_tries=3)
def judge_answer(client, model, task, question, correct_answer, response, abstention=False):
    """Use LLM judge to evaluate if the response is correct."""
    prompt = get_anscheck_prompt(task, question, correct_answer, response, abstention)
    
    result = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a fair and precise evaluator. Answer only yes or no."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=10,
        temperature=0,
    )
    
    judgment = result.choices[0].message.content.strip().lower()
    return "yes" in judgment


def evaluate(hyp_file, ref_file, judge_model="google/gemini-2.5-flash-lite"):
    """Evaluate hypotheses against references."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: Set OPENROUTER_API_KEY or OPENAI_API_KEY environment variable")
        sys.exit(1)

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    # Load hypotheses
    hypotheses = {}
    with open(hyp_file) as f:
        for line in f:
            h = json.loads(line.strip())
            hypotheses[h["question_id"]] = h["hypothesis"]

    # Load references
    with open(ref_file) as f:
        references = json.load(f)

    print(f"Evaluating {len(hypotheses)} questions with judge: {judge_model}")
    print(f"Reference file: {ref_file}")
    print()

    results = []
    correct = 0
    total = 0
    errors = 0

    for ref in tqdm(references):
        qid = ref["question_id"]
        if qid not in hypotheses:
            continue

        task = ref["question_type"]
        if qid.endswith("_abs"):
            task = "abstention"

        question = ref["question"]
        answer = ref["answer"]
        response = hypotheses[qid]
        abstention = task == "abstention"

        try:
            is_correct = judge_answer(client, judge_model, task, question, answer, response, abstention)
            if is_correct:
                correct += 1
            total += 1
            results.append({
                "question_id": qid,
                "task": task,
                "correct": is_correct,
                "question": question,
                "expected": answer,
                "response": response[:200],
            })
        except Exception as e:
            errors += 1
            results.append({
                "question_id": qid,
                "task": task,
                "correct": False,
                "error": str(e)[:200],
            })

    # Print results
    print(f"\n{'='*60}")
    print(f"NEXUS LongMemEval Results")
    print(f"{'='*60}")
    print(f"Judge model: {judge_model}")
    print(f"Total evaluated: {total}")
    print(f"Correct: {correct}")
    print(f"Errors: {errors}")
    if total > 0:
        print(f"\nOverall Accuracy: {correct/total*100:.1f}%")
    print()

    # Per-type breakdown
    from collections import defaultdict
    by_type = defaultdict(lambda: {"correct": 0, "total": 0})
    for r in results:
        t = r.get("task", "unknown")
        by_type[t]["total"] += 1
        if r.get("correct"):
            by_type[t]["correct"] += 1

    print("Per-type breakdown:")
    print(f"{'Type':<30} {'Correct':>8} {'Total':>6} {'Accuracy':>10}")
    print("-" * 60)
    for t in sorted(by_type.keys()):
        stats = by_type[t]
        acc = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"{t:<30} {stats['correct']:>8} {stats['total']:>6} {acc:>9.1f}%")

    # Save detailed results
    result_file = hyp_file + ".eval-results-v2.json"
    with open(result_file, "w") as f:
        json.dump({
            "summary": {
                "judge_model": judge_model,
                "total": total,
                "correct": correct,
                "accuracy": correct / total * 100 if total > 0 else 0,
                "by_type": {t: {
                    "correct": s["correct"],
                    "total": s["total"],
                    "accuracy": s["correct"] / s["total"] * 100 if s["total"] > 0 else 0,
                } for t, s in by_type.items()},
            },
            "details": results,
        }, f, indent=2)

    print(f"\nDetailed results saved to: {result_file}")

    return correct / total * 100 if total > 0 else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python evaluate_nexus_v2.py <hypotheses.jsonl> <reference.json> [judge_model]")
        print("  judge_model: google/gemini-2.5-flash-lite (default), openai/gpt-4o, etc.")
        sys.exit(1)

    hyp_file = sys.argv[1]
    ref_file = sys.argv[2]
    judge_model = sys.argv[3] if len(sys.argv) > 3 else "google/gemini-2.5-flash-lite"

    evaluate(hyp_file, ref_file, judge_model)
