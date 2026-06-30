# ONE Local Model Inventory

Last updated: 2026-06-30

This inventory tracks which local models and runtimes are installed for ONE on the local RTX 3070 Ti 8GB workstation.

## Active Routing

| Scope | Engine | Model | Status |
| --- | --- | --- | --- |
| ONE router / chat | Ollama | llama3.1:8b | Active |
| Fast fallback | Ollama | qwen3.5:2b | Installed |
| Heavy local reasoning | Ollama | qwen3.6:latest | Installed, use carefully on 8GB VRAM |
| Nemotron / NVIDIA NIM | NVIDIA OpenAI-compatible API | unset | Configured slot, inactive until `NVIDIA_API_KEY` and exact model id are set |
| IA image generation | Local FLUX API | black-forest-labs/FLUX.1-schnell | Wired as default image provider; model access requires accepted Hugging Face license + token |

## Installed Local Capabilities

| Capability | Runtime | Installed Item | Notes |
| --- | --- | --- | --- |
| Reasoning / agent brain | Ollama | llama3.1:8b | Pulled and smoke-tested locally |
| Fast reasoning fallback | Ollama | qwen3.5:2b | Existing local model |
| Heavy reasoning | Ollama | qwen3.6:latest | Existing local model; memory-heavy |
| OCR / document parsing | Python | paddleocr 3.7.0 + paddlepaddle 3.3.1 | Installed in ONE venv; PP-OCRv6 medium detection/recognition weights cached locally |
| Speech-to-text | Python | faster-whisper | Existing local speech stack |
| Local image generation | Python/FastAPI/diffusers | ONE FLUX server on `127.0.0.1:8188` | Server installed and autostarted; weights download after `HF_TOKEN` is configured |

## NVIDIA Build Models From The RTX List

| NVIDIA listing | Local status on this machine | Decision |
| --- | --- | --- |
| llama-3.1-8b-instruct | Installed via Ollama as `llama3.1:8b` | Use as default ONE brain |
| paddleocr | Installed via Python package stack | PP-OCRv6 medium detection and recognition weights cached locally |
| parakeet-ctc-0.6b-asr | Not installed as NVIDIA package | Keep `faster-whisper` active; Parakeet needs NeMo/Riva/NIM setup |
| nv-yolox-page-elements-v1 | Not installed | Needs NVIDIA/NGC model package or custom ONNX/TensorRT path |
| FLUX.1-schnell | Local ONE FLUX server wired | Requires Hugging Face gated-model access; set `HF_TOKEN` after accepting the license |
| FLUX.1-dev | Not installed | Too heavy for default 8GB workflow; use only as a dedicated image job |
| TRELLIS | Not installed | Heavy 3D workflow; not a default ONE dependency |
| Studio Voice | Not installed | NVIDIA package/runtime needed; existing local TTS/STT should stay active for now |

## Cloud / Not Local On RTX 3070 Ti 8GB

| Model | Reason |
| --- | --- |
| nemotron-3-ultra-550b-a55b | Too large for 8GB local GPU; use NVIDIA NIM/cloud endpoint only |
| kimi-k2.6 | Too large for 8GB local GPU; endpoint/hosted only |
| deepseek-v4-pro | Too large for 8GB local GPU; endpoint/hosted only |
| glm-5.1 | Too large for 8GB local GPU; endpoint/hosted only |

## Cache Policy

ONE startup redirects model caches into local runtime data:

| Variable | Local path |
| --- | --- |
| `PADDLE_PDX_CACHE_HOME` | `data/model_cache/paddlex` |
| `HF_HOME` | `data/model_cache/huggingface` |
| `TORCH_HOME` | `data/model_cache/torch` |
| `XDG_CACHE_HOME` | `data/model_cache/xdg` |
| `HOME` / `USERPROFILE` for ONE child processes | `data/runtime_home` |

## FLUX Setup Notes

Local FLUX is the default image route through `ONE_IMAGE_PROVIDER=flux`.

1. Accept access for `black-forest-labs/FLUX.1-schnell` on Hugging Face.
2. Save the token locally with `set-flux-hf-token.ps1 -Token <token>`.
3. Restart with `stop-one.ps1` then `start-one.ps1`.
4. First generation downloads the FLUX weights into `data/model_cache/huggingface`.
