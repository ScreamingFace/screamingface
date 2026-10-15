# VENDORED COPY — source:
# https://github.com/josejg/instruction_following_eval/blob/0c495b2f95155e8b10acb919ae283bfb4d5be6e2/instruction_following_eval/evaluation.py
# Local changes (each one required to run inside this offline package; the verdict
# logic itself is byte-identical to the source):
#   1. This banner.
#   2. The import rewritten to relative (`from . import instructions_registry`).
#   3. CLI/file-IO-only symbols REMOVED: the typer/rich imports, `DEFAULT_FILE`,
#      `get_examples`, `print_report`, `main`, and the `__main__` block — they need
#      typer/rich (not dependencies here) and read the filesystem.
#   4. `ensure_nltk_resource` and its call inside `evaluate_instruction_following`
#      REMOVED: it downloads NLTK corpora at run time, which the offline Runner Job
#      forbids (see vendor/__init__.py). Callers must provision tokenizer data
#      first (tests use `..grading.configure_nltk` / the ifeval_nltk_data fixture).
# Do not edit.
import dataclasses
from typing import Dict, List, Union, Any

from . import instructions_registry


@dataclasses.dataclass
class InputExample:
    key: int
    instruction_id_list: List[str]
    prompt: str
    kwargs: List[Dict[str, Any]]

@dataclasses.dataclass
class OutputExample:
    instruction_id_list: List[str]
    prompt: str
    response: str
    follow_all_instructions: bool
    follow_instruction_list: List[bool]

def mean(numbers: List[float]) -> float:
    """Calculate the mean of a list of numbers."""
    return sum(numbers) / len(numbers) if numbers else 0.0

def instruction_mean(results: List[OutputExample]) -> float:
    """Calculate the mean accuracy across all instructions."""
    all_instructions = [inst for result in results for inst in result.follow_instruction_list]
    return mean(all_instructions)

def dict_to_input_example(example: Dict[str, Any]) -> InputExample:
    """Convert a dictionary to an InputExample."""
    return InputExample(
        key=example["key"],
        instruction_id_list=example["instruction_id_list"],
        prompt=example["prompt"],
        kwargs=example["kwargs"]
    )

def test_instruction_following(example: Union[Dict[str, Any], InputExample], response: str, strict: bool = True) -> OutputExample:
    """Tests response to see if instructions are followed."""
    if isinstance(example, dict):
        example = dict_to_input_example(example)

    is_following_list = []

    if not strict:
        responses = [
            response,
            response.replace("*", ""),
            "\n".join(response.split("\n")[1:]).strip(),
            "\n".join(response.split("\n")[:-1]).strip(),
            "\n".join(response.split("\n")[1:-1]).strip(),
        ]
        responses += [r.replace("*", "") for r in responses[2:]]
    else:
        responses = [response]

    for index, instruction_id in enumerate(example.instruction_id_list):
        instruction_cls = instructions_registry.INSTRUCTION_DICT[instruction_id]
        instruction = instruction_cls(instruction_id)

        instruction.build_description(**example.kwargs[index])
        args = instruction.get_instruction_args()
        if args and "prompt" in args:
            instruction.build_description(prompt=example.prompt)

        is_following = any(r.strip() and instruction.check_following(r) for r in responses)
        is_following_list.append(is_following)

    return OutputExample(
        instruction_id_list=example.instruction_id_list,
        prompt=example.prompt,
        response=response,
        follow_all_instructions=all(is_following_list),
        follow_instruction_list=is_following_list,
    )

def evaluate_instruction_following(examples: List[Dict[str, Any]], responses: List[str]) -> Dict[str, float]:
    if len(examples) != len(responses):
        raise ValueError("The number of examples and responses must be the same.")

    input_examples = [dict_to_input_example(ex) for ex in examples]
    strict_results = [test_instruction_following(ex, resp, strict=True) for ex, resp in zip(input_examples, responses)]
    loose_results = [test_instruction_following(ex, resp, strict=False) for ex, resp in zip(input_examples, responses)]

    return {
        "prompt_level_strict_accuracy": mean([r.follow_all_instructions for r in strict_results]),
        "inst_level_strict_accuracy": instruction_mean(strict_results),
        "prompt_level_loose_accuracy": mean([r.follow_all_instructions for r in loose_results]),
        "inst_level_loose_accuracy": instruction_mean(loose_results),
    }
