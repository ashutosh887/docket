# Data: CHECK-MAT

Docket is measured on CHECK-MAT: 122 scanned handwritten solutions to Russian Unified State Exam (EGE) profile mathematics tasks 13 to 19, each with the expert grade, plus the official FIPI criteria and estimation examples.

- Code and images: https://github.com/Karifannaa/Auto-check-EGE-math
- Hugging Face copy: https://huggingface.co/datasets/Karifannaa/EGE_Math_Solutions_Assessment_Benchmark
- Paper: Khrulev, R. (2025). CHECK-MAT: Checking Hand-Written Mathematical Answers for the Russian Unified State Exam. https://arxiv.org/abs/2507.22958

## Licence (read 4 Nov 2026)
- The GitHub repository has no LICENSE file (the GitHub API reports `license: null`), but its README states: "The source code and dataset for this research are available under the MIT License. This permissive license allows for reuse, modification, and distribution, both in academic and commercial settings, provided that the original copyright and license notice are included."
- The Hugging Face dataset card sets `license: other` and says: "This dataset is provided for research and educational purposes."
- Docket does not commit the images. Fetch them yourself.

## Fetch
```
python scripts/fetch_checkmat.py
```
This clones the repository into `data/raw/Auto-check-EGE-math` (git-ignored). Docket reads `dataset_benchmark/<task>/<task.example>/<task.example.solution>/without_answer/*.png` as the student's pages (in `_part_N_` order) and `<task.example>_solve_true.png` as the reference (task statement, official solution and criteria table). The expert grade is the number in each file name (`..._estimate_2.png` is 2 points).

What is in the folder (counted on 4 Nov): 152 student pages without answers across 122 solutions; 21 task-13 solutions, 18 task-14, 19 task-15, 17 task-16, 15 task-17, 16 task-18, 16 task-19 (counts from the dataset card).

## Upload a class set for the Lambda
```
python scripts/fetch_checkmat.py --upload s3://<bucket>/scripts --task 13 --n 10
```
Each script goes to `scripts/<scriptId>/` with its pages and its reference image, the layout `docket.aws_handler` reads.

## Say it plainly
Russian maths scripts stand in for any scheme-marked handwritten exam. The scheme code in `src/docket/scheme.py` restates the FIPI criteria table per task as yes/no observations plus a level rule; the Russian original sits beside each task as `official`. Scheme `v2` is a demonstration amendment to task 13, not an FIPI change.
