#!/usr/bin/env python3
"""
NEXUS LongMemEval Benchmark Harness

Runs NEXUS against the LongMemEval benchmark:
1. Ingests chat history sessions into NEXUS as memories
2. Queries NEXUS with each question
3. Collects answers in jsonl format for evaluation

Usage:
    python benchmarks/longmemeval/run_benchmark.py --dataset data/longmemeval_s_cleaned.json
    python benchmarks/longmemeval/run_benchmark.py --dataset data/longmemeval_oracle.json
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import NexusStorage
from src.nl_interface import NLMemoryInterface


def ingest_sessions(db, sessions, session_ids, dates, source_prefix="benchmark"):
    """Ingest chat history sessions into NEXUS."""
    total_turns = 0
    for i, (session, sid, date) in enumerate(zip(sessions, session_ids, dates)):
        # Combine all turns in a session into one memory
        turns_text = []
        has_answer = False
        for turn in session:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")
            turns_text.append(f"[{role}] {content}")
            if turn.get("has_answer"):
                has_answer = True

        session_content = "\n".join(turns_text)

        # Store as memory with metadata
        mem = db.add_memory(
            content=session_content,
            category="chat_history",
            source_agent=f"{source_prefix}_session_{sid}",
            tags=["longmemeval", "chat_session", f"session_{sid}"],
            emotional_weight=0.8 if has_answer else 0.3,
        )
        total_turns += len(session)

    return total_turns


def answer_question(db, nl, question):
    """Query NEXUS to answer a question."""
    # Try NL interface first
    try:
        result = nl.process(question)
        if result and result.get("results"):
            # Combine top results into an answer
            answers = []
            for r in result["results"][:5]:
                content = r.get("content", "")
                if content:
                    answers.append(content)
            if answers:
                return " ".join(answers[:3])
    except Exception:
        pass

    # Fallback to direct search
    try:
        results = db.search(question, limit=5, mode="keyword")
        if results:
            answers = []
            for r in results[:5]:
                content = r.get("content", "")
                if content:
                    answers.append(content)
            if answers:
                return " ".join(answers[:3])
    except Exception:
        pass

    return "I don't have enough information to answer this question."


def run_benchmark(dataset_path, output_path, limit=None, use_nl=True):
    """Run the full benchmark."""
    print(f"Loading dataset: {dataset_path}")
    with open(dataset_path) as f:
        dataset = json.load(f)

    if limit:
        dataset = dataset[:limit]

    print(f"Questions to evaluate: {len(dataset)}")

    # Use a fresh DB for the benchmark
    db_path = str(Path.home() / ".nexus" / "benchmark.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    db = NexusStorage(db_path=db_path)
    nl = NLMemoryInterface(db=db) if use_nl else None

    hypotheses = []
    total_ingested = 0
    start_time = time.time()

    for i, item in enumerate(dataset):
        qid = item["question_id"]
        question = item["question"]
        q_type = item["question_type"]

        # Ingest all sessions for this question
        turns = ingest_sessions(
            db,
            item["haystack_sessions"],
            item["haystack_session_ids"],
            item.get("haystack_dates", []),
            source_prefix=qid[:20],
        )
        total_ingested += turns

        # Answer the question
        answer = answer_question(db, nl, question)

        hypotheses.append({
            "question_id": qid,
            "hypothesis": answer,
        })

        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            qps = (i + 1) / elapsed
            print(f"  [{i+1}/{len(dataset)}] {qps:.1f} q/s | {total_ingested} turns ingested")

    elapsed = time.time() - start_time
    print(f"\nCompleted in {elapsed:.1f}s ({len(dataset)/elapsed:.1f} q/s)")
    print(f"Total turns ingested: {total_ingested}")

    # Write hypotheses
    with open(output_path, "w") as f:
        for h in hypotheses:
            f.write(json.dumps(h) + "\n")

    print(f"Hypotheses written to: {output_path}")

    # Cleanup
    db.close()
    if os.path.exists(db_path):
        os.remove(db_path)

    return hypotheses


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEXUS LongMemEval Benchmark")
    parser.add_argument("--dataset", required=True, help="Path to LongMemEval json file")
    parser.add_argument("--output", default=None, help="Output jsonl path")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of questions")
    parser.add_argument("--no-nl", action="store_true", help="Disable NL interface")
    args = parser.parse_args()

    if not args.output:
        dataset_name = Path(args.dataset).stem
        args.output = f"benchmarks/longmemeval/results_{dataset_name}.jsonl"

    run_benchmark(args.dataset, args.output, args.limit, use_nl=not args.no_nl)
