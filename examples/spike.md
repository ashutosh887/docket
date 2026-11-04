# Hour-0 spike, 4 Nov 2026 (IST)

Script: CHECK-MAT `13/13.1/13.1.1/without_answer/13.1.1_solve_estimate_2.png` (official grade 2).
Prompt: "Transcribe the first three handwritten lines of this exam script, then state the final answer to part b)."

| Reader | API | Answered | Seconds | Raw first lines |
|---|---|---|---|---|
| `groq:qwen/qwen3.8-27b` | Groq OpenAI-compatible chat, image as data URL | yes, 13:02 | 82.4 | `задача 13` / `a) cos 2x - √2 sin (x + π) = 1` / `Final answer to part b): -3π; -2π; -13/4 π` |
| `gemini:gemini-3-flash-preview` | google-genai SDK `models.generate_content` | yes, 13:04 | 139.2 | `1. Задача 13` / `2. а) $\cos 2x - \sqrt{2} \sin(x+\pi) = 1$` / `The final answer to part b) is: $-3\pi; -2\pi; -\frac{13}{4}\pi$.` |
| `gemini:gemini-2.5-flash` | google-genai SDK | no | 100.3 | `404 NOT_FOUND ... no longer available to new users. Please update your code to use models/gemini-3.8-flash` |
| `gemini:gemini-3.8-flash` | google-genai SDK | no | 106.8 | `503 UNAVAILABLE ... experiencing high demand` |
| `gemini:gemini-flash-latest` | google-genai SDK | no | 116.3 | `503 UNAVAILABLE` |
| `gemini:gemma-4-31b-it` | google-genai SDK | no | 121.1 | `500 INTERNAL` |
| `cohere:command-a-vision-07-2025` | Cohere ClientV2 chat | no (twice, 13:02 and 13:07) | 57.8, 35.9 | `TooManyRequestsError ... x-trial-endpoint-call-limit: 20, x-trial-endpoint-call-remaining: 17` |

Reader A is Qwen (Alibaba) on Groq; reader B is Gemini (Google). Different model families.

Structured per-criterion reading through a Strands `Agent` with `structured_output_model` (13:10 to 13:12 IST, both in parallel, 84.7 s wall): both readers returned K1, K2, K3 all met for 13.1.1, so the scheme gives 2 points, the official grade.

## KMS (13:06 IST)
- Key `arn:aws:kms:ap-south-1:960149837193:key/3e29a662-62e2-4526-aacf-28f7b0722921`, alias `alias/docket-credentials`, ECC_NIST_P256, SIGN_VERIFY, tag `project=docket`, created with profile `cyclosentry` (alias did not exist before).
- `Sign` (MessageType DIGEST, ECDSA_SHA_256) then KMS `Verify`: `SignatureValid: True`. Local verify of the same signature with the exported public key (cryptography, prehashed SHA-256): passed.
- Public key: `examples/docket-public.pem` (SPKI PEM).
