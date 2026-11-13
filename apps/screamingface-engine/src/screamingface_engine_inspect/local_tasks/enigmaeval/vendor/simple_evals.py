# pyright: reportMissingImports=false
# WHY file-level: numpy and Pillow come with the `inspect` extra, absent in the default
# (extra-less) install; this directory is also outside pyright's scope (pyproject.toml).
"""COPIED third-party code: the EnigmaEval authors' answer reader, normaliser and prompt pieces.

Do not edit below this header. Copied from centerforaisafety/simple-evals, branch ``dev``, at
commit 6614edf59833140fb77e61758bbb2674b54a445e (``main`` has no EnigmaEval). MIT licence,
Copyright 2025 Scale AI and the Center for AI Safety (``LICENSE`` beside this file is the code
part of the authors' ``enigmaeval/LICENSE.md``). Sources, at the pinned commit:

- ``standardize`` (L38-L47), ``extract_answer_from_response`` (L65-L76) and
  ``evaluate_answer`` (L78-L88): https://github.com/centerforaisafety/simple-evals/blob/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval/enigmaeval_eval.py#L38-L88
- ``_pil_to_base64_png`` (L123-L133) and ``get_answer_type`` (L205-L219):
  https://github.com/centerforaisafety/simple-evals/blob/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval/enigmaeval_utils.py#L123-L219
- ``STANDARD_TIPS``: https://github.com/centerforaisafety/simple-evals/blob/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval/prompt_templates/standard_tips.txt
- ``MIT_TIPS``: https://github.com/centerforaisafety/simple-evals/blob/6614edf59833140fb77e61758bbb2674b54a445e/enigmaeval/prompt_templates/mit_tips.txt

The ONLY changes we made:

1. This header. The authors' files hold more than these functions (a CLI, an async runner, the
   dataset fetch); only what the Task calls is copied.
2. Whitespace-only lines inside the functions are emptied, because the repo's
   ``trailing-whitespace`` hook rewrites them; no other line of theirs ends in whitespace, so
   behaviour is unchanged. ``test_local_task_enigmaeval.py`` strips trailing whitespace from
   each function here and demands the sha256 the authors' function gives under the same strip.
3. The two tips files are string constants, so the Task's source digest covers them; each
   constant's UTF-8 bytes hash to the authors' file.

What is NOT copied, and why: the authors' ``PromptMaker`` builds its system prompt with an
f-string whose first line ends in a space, which the same hook would strip, changing what the
Candidate reads. It is restated in ``..enigmaeval`` instead, and a test pins its output to the
authors' builder's output for real rows.

INVARIANT: this file IS how the exam reads and marks an answer. Upstream quirks stay: a gold
answer with a comma compares as a set of its parts; a ``|`` in the gold answer lists
alternatives; a reply with no ``<answer>`` tags is wrong.
"""

import base64
import io
import re

import numpy as np

def standardize(input_string: str) -> str:
    """Standardize answer strings for comparison."""
    if input_string is np.nan or input_string is None:
        return ""

    input_string = str(input_string).lower()
    if "," in input_string:
        return set([standardize(s) for s in input_string.split(",")])
    else:
        return re.sub(r"[^a-zA-Z0-9]", "", input_string)


def extract_answer_from_response(response: str) -> str:
    """Extract the answer from the model response using XML tags."""
    if not isinstance(response, str):
        return None

    # Extract from <answer></answer> XML tags
    xml_match = re.search(r'<answer>(.*?)</answer>', response, re.IGNORECASE | re.DOTALL)
    if xml_match:
        answer = xml_match.group(1).strip()
        return answer

    return None

def evaluate_answer(gt_answer: str, model_answer: str) -> bool:
    """Evaluate if the model answer matches the ground truth."""
    if model_answer is None:
        return False

    if "|" in gt_answer:
        # Multiple acceptable answers
        return standardize(model_answer) in [standardize(a) for a in gt_answer.split("|")]
    else:
        # Single answer
        return standardize(model_answer) == standardize(gt_answer)


def _pil_to_base64_png(img) -> str:
    """Convert a PIL.Image (as returned by HF datasets v2) to a data: URI base64 PNG."""
    if img is None:
        return None
    buf = io.BytesIO()
    # Ensure mode is something safe for PNG
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def get_answer_type(answer: str):
    """Determine the answer type and format based on the answer string."""
    if "," in answer:
        if answer.count(",") == 1:
            answer_type = "pair of words/phrases"
            answer_format = "answer1, answer2"
        else:
            answer_type = "comma-separated list of words/phrases"
            answer_format = "answer1, answer2, ..."
    else:
        answer_type = "word or short phrase"
        answer_format = "answer"

    answer_format = f"<answer>{answer_format}</answer>"
    return answer_type, answer_format


STANDARD_TIPS = """\
General Tips:
- Puzzles will often have multiple steps to get to the answer word. You can usually tell you are on the right track if the intermediate answers agree with the title, flavor, or theme of the puzzle.
- You can usually find hints in the introductory text. For example references to “in the dark” or “sight” are often hints something is encoded with braille.
- Puzzles often incorporate acrostics: a clue where the first letter, syllable, or word of each line, paragraph, or other recurring feature spells out a word or message.
- If you end up with a garbled “alphabet soup”, then look for a clue on how to order them.
- Indexing is one of the most common puzzle mechanisms. Try indexing when you have a list of words or phrases and a corresponding list of numbers. Count into the word or phrase by the given number and record the letter in that position. For example: "2 Cake, 6 Pudding, 5 Shortening" gives you "ant".
- Alpha-numeric codes are also very common. If you end up with a list of numbers try replacing the numbers with the corresponding letters like this: 1 = A, 2 = B, 3 = C... 26 = Z. Occasionally, these types of codes will “wrap around”, so don’t despair if you see a number greater than 26. Just subtract 26 and try again. In this scenario 27 (27-26 = 1) = A, 28 (28-26 = 2) = B etc. If you try this and it doesn’t work, try other numeric codes such as ASCII.
- Often a puzzle repeats a strategy multiple times.

You will likely need to backtrack frequently, so make sure to write out your steps as you go.
If you get stuck, try to think of a new way to approach the puzzle. Try:
- Rereading the title and the flavor text. These are the most important hints about what type of strategies, themes or cultural references might be used to solve the puzzle.
- Checking for pop culture references
- Checking for references to a song/poem/book/movie/TV show

For strings, examples of strategies you might try include:
- Alphabetizing
- Using leftover letters to spell something
- Rearranging the letters (aka anagrams or "transposing")
- Seeing if there are any acronyms
- Diagonalizing (taking the first letter of the first answer, the second letter of the second answer, etc.)
- Looking for unusual letter frequencies
- Puns and homophones
- Shifting from letters to numbers

For numbers, try:
- Shifting from numbers to letters
- Using it as a phone number
- Treating numbers as dates
- Treating numbers as ASCII numbers
- Seeing if there are any strange sequences
- Seeing if prime numbers are involved

For images, try:
- Looking at it in a mirror
- Squinting at it from far away
- Tilting it
- Looking at it upside down
- Looking through it
- Transcribing it neatly
"""

MIT_TIPS = """\
General Tips:
- Puzzles will often have multiple steps to get to the answer word. You can usually tell you are on the right track if the intermediate answers agree with the title, flavor, or theme of the puzzle.
- You can usually find hints in the introductory text. For example references to “in the dark” or “sight” are often hints something is encoded with braille.
- Puzzles often incorporate acrostics: a clue where the first letter, syllable, or word of each line, paragraph, or other recurring feature spells out a word or message.
- If you end up with a garbled “alphabet soup”, then look for a clue on how to order them.
- Indexing is one of the most common puzzle mechanisms. Try indexing when you have a list of words or phrases and a corresponding list of numbers. Count into the word or phrase by the given number and record the letter in that position. For example: "2 Cake, 6 Pudding, 5 Shortening" gives you "ant".
- Alpha-numeric codes are also very common. If you end up with a list of numbers try replacing the numbers with the corresponding letters like this: 1 = A, 2 = B, 3 = C... 26 = Z. Occasionally, these types of codes will “wrap around”, so don’t despair if you see a number greater than 26. Just subtract 26 and try again. In this scenario 27 (27-26 = 1) = A, 28 (28-26 = 2) = B etc. If you try this and it doesn’t work, try other numeric codes such as ASCII.
- Often a puzzle repeats a strategy multiple times.

You will likely need to backtrack frequently, so make sure to write out your steps as you go.
If you get stuck, try to think of a new way to approach the puzzle. Try:
- Rereading the title and the flavor text. These are the most important hints about what type of strategies, themes or cultural references might be used to solve the puzzle.
- Checking for pop culture references
- Checking for references to a song/poem/book/movie/TV show

For strings, examples of strategies you might try include:
- Alphabetizing
- Using leftover letters to spell something
- Rearranging the letters (aka anagrams or "transposing")
- Looking for unusual letter frequencies
- Puns and homophones
- Determining if it is a Rot 13/Caesar shift in general
- Shifting from letters to numbers
- Treating letters as protein sequences
- Treating letters as call letters
- Turning it into a cryptic crossword clue
- Seeing if these words relate to song lyrics
- Seeing if there are any acronyms of phrases
- Diagonalizing (taking the first letter of the first answer, the second letter of the second, etc.)
- Looking at a computer keyboard

For numbers, try:
- Graphing it functionally
- Graphing it parametrically
- Checking to see if your numbers are in the right base (including hex)
- Shifting from numbers to letters
- Using it as a phone number
- Using it as an IP address
- Matching numbers to MIT buildings or courses
- Treating numbers as dates
- Treating numbers as atomic weights, numbers, etc. (if chemistry themed)
- Treating numbers as latitude/longitude or GPS coordinates
- Treating numbers as radio stations
- Treating numbers as ASCII numbers
- Treating numbers as PLU numbers (if grocery themed)
- Treating numbers as ISBN numbers (if book themed)
- Seeing if there are any strange sequences
- Seeing if prime numbers are involved
- Seeing if fundamental constants are involved
- Asking what other numbers are close to the one you have

For images, try:
- Looking at it in a mirror
- Squinting at it from far away
- Tilting it
- Looking at it upside down
- Looking through it
- Transcribing it neatly
- Transcribing it on graph paper
- Connecting the dots
- Overlaying it on a map of MIT

For symbolic messages, try:
- Braille, Morse code, semaphores
- Binary or other encodings
- Using the Library of Congress or Dewey decimal system (if book-themed)
"""
