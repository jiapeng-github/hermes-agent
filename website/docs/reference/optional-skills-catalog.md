---
sidebar_position: 9
title: "Optional Skills Catalog"
description: "Official optional skills shipped with hermes-agent — install via hermes skills install official/<category>/<skill>"
---

# Optional Skills Catalog

Optional skills ship with hermes-agent under `optional-skills/` but are **not active by default**. Install them explicitly:

```bash
hermes skills install official/<category>/<skill>
```

For example:

```bash
hermes skills install official/blockchain/solana
hermes skills install official/mlops/flash-attention
```

Each skill below links to a dedicated page with its full definition, setup, and usage.

To uninstall:

```bash
hermes skills uninstall <skill-name>
```

## apple

| Skill | Description |
|-------|-------------|
| [**apple-notes**](/docs/user-guide/skills/optional/apple/apple-apple-notes) | Manage Apple Notes via memo CLI: create, search, edit. |
| [**apple-reminders**](/docs/user-guide/skills/optional/apple/apple-apple-reminders) | Apple Reminders via remindctl: add, list, complete. |
| [**findmy**](/docs/user-guide/skills/optional/apple/apple-findmy) | Track Apple devices/AirTags via FindMy.app on macOS. |
| [**imessage**](/docs/user-guide/skills/optional/apple/apple-imessage) | Send and receive iMessages/SMS via the imsg CLI on macOS. |

## autonomous-ai-agents

| Skill | Description |
|-------|-------------|
| [**antigravity-cli**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-antigravity-cli) | Operate the Antigravity CLI (agy): plugins, auth, sandbox. |
| [**blackbox**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-blackbox) | Delegate coding tasks to the Blackbox AI multi-model CLI. |
| [**grok**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-grok) | Delegate coding to xAI Grok Build CLI (features, PRs). |
| [**hermes-agent**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-hermes-agent) | Use, configure, theme, extend, and orchestrate Hermes Agent. |
| [**honcho**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-honcho) | Configure and troubleshoot Honcho memory for Hermes. |
| [**merge-reconciler**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-merge-reconciler) | Neutral third-party resolution of agent merge conflicts. |
| [**opencode**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-opencode) | Delegate coding to OpenCode CLI (features, PR review). |
| [**openhands**](/docs/user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-openhands) | Delegate coding to OpenHands CLI (model-agnostic, LiteLLM). |

## blockchain

| Skill | Description |
|-------|-------------|
| [**evm**](/docs/user-guide/skills/optional/blockchain/blockchain-evm) | Read-only EVM client: wallets, tokens, gas across 8 chains. |
| [**hyperliquid**](/docs/user-guide/skills/optional/blockchain/blockchain-hyperliquid) | Hyperliquid market data, account history, trade review. |
| [**solana**](/docs/user-guide/skills/optional/blockchain/blockchain-solana) | Query Solana wallets, tokens, txs, and NFTs in USD. |

## communication

| Skill | Description |
|-------|-------------|
| [**one-three-one-rule**](/docs/user-guide/skills/optional/communication/communication-one-three-one-rule) | 1-3-1 decision briefs: problem, three options, one pick. |

## computer-use

| Skill | Description |
|-------|-------------|
| [**computer-use**](/docs/user-guide/skills/optional/computer-use/computer-use-computer-use) | Drive the desktop in the background without stealing focus. |

## creative

| Skill | Description |
|-------|-------------|
| [**architecture-diagram**](/docs/user-guide/skills/optional/creative/creative-architecture-diagram) | Dark-themed SVG architecture/cloud/infra diagrams as HTML. |
| [**ascii-art**](/docs/user-guide/skills/optional/creative/creative-ascii-art) | ASCII art: pyfiglet, cowsay, boxes, image-to-ascii. |
| [**ascii-video**](/docs/user-guide/skills/optional/creative/creative-ascii-video) | ASCII video: convert video/audio to colored ASCII MP4/GIF. |
| [**audiocraft-audio-generation**](/docs/user-guide/skills/optional/creative/creative-audiocraft-audio-generation) | AudioCraft: MusicGen text-to-music, AudioGen text-to-sound. |
| [**baoyu-article-illustrator**](/docs/user-guide/skills/optional/creative/creative-baoyu-article-illustrator) | Article illustrations: type × style × palette consistency. |
| [**baoyu-comic**](/docs/user-guide/skills/optional/creative/creative-baoyu-comic) | Knowledge comics (知识漫画): educational, biography, tutorial. |
| [**baoyu-infographic**](/docs/user-guide/skills/optional/creative/creative-baoyu-infographic) | Infographics: 21 layouts x 21 styles (信息图, 可视化). |
| [**claude-design**](/docs/user-guide/skills/optional/creative/creative-claude-design) | Design one-off HTML artifacts (landing, deck, prototype). |
| [**comfyui**](/docs/user-guide/skills/optional/creative/creative-comfyui) | Generate images, video, and audio via diffusion workflows. |
| [**concept-diagrams**](/docs/user-guide/skills/optional/creative/creative-concept-diagrams) | Generate flat, minimal educational SVG visuals as HTML. |
| [**creative-ideation**](/docs/user-guide/skills/optional/creative/creative-creative-ideation) | Generate ideas via named methods from creative practice. |
| [**excalidraw**](/docs/user-guide/skills/optional/creative/creative-excalidraw) | Hand-drawn Excalidraw JSON diagrams (arch, flow, seq). |
| [**heartmula**](/docs/user-guide/skills/optional/creative/creative-heartmula) | HeartMuLa: Suno-like song generation from lyrics + tags. |
| [**hyperframes**](/docs/user-guide/skills/optional/creative/creative-hyperframes) | Render MP4/WebM videos from HTML compositions. |
| [**kanban-video-orchestrator**](/docs/user-guide/skills/optional/creative/creative-kanban-video-orchestrator) | Plan and run multi-agent video production pipelines. |
| [**manim-video**](/docs/user-guide/skills/optional/creative/creative-manim-video) | Manim CE animations: 3Blue1Brown math/algo videos. |
| [**meme-generation**](/docs/user-guide/skills/optional/creative/creative-meme-generation) | Create meme PNGs from templates with Pillow text overlay. |
| [**p5js**](/docs/user-guide/skills/optional/creative/creative-p5js) | p5.js sketches: gen art, shaders, interactive, 3D. |
| [**pixel-art**](/docs/user-guide/skills/optional/creative/creative-pixel-art) | Pixel art w/ era palettes (NES, Game Boy, PICO-8). |
| [**popular-web-designs**](/docs/user-guide/skills/optional/creative/creative-popular-web-designs) | 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS. |
| [**pretext**](/docs/user-guide/skills/optional/creative/creative-pretext) | Build creative browser demos with DOM-free text layout. |
| [**sketch**](/docs/user-guide/skills/optional/creative/creative-sketch) | Throwaway HTML mockups: 2-3 design variants to compare. |
| [**social-media-content-calendar**](/docs/user-guide/skills/optional/creative/creative-social-media-content-calendar) | Plan multi-platform social campaigns: briefs to posting. |
| [**songwriting-and-ai-music**](/docs/user-guide/skills/optional/creative/creative-songwriting-and-ai-music) | Songwriting craft and Suno AI music prompts. |
| [**tldraw-offline**](/docs/user-guide/skills/optional/creative/creative-tldraw-offline) | Drive and script tldraw offline canvases with an agent. |
| [**touchdesigner-mcp**](/docs/user-guide/skills/optional/creative/creative-touchdesigner-mcp) | Control TouchDesigner via twozero MCP. |
| [**unreal-mcp**](/docs/user-guide/skills/optional/creative/creative-unreal-mcp) | Automate Unreal Engine editor scenes, actors, and renders. |

## data-science

| Skill | Description |
|-------|-------------|
| [**jupyter-notebook**](/docs/user-guide/skills/optional/data-science/data-science-jupyter-live-kernel) | Iterative Python via live Jupyter kernel (hamelnb). |
| [**jupyter-notebook**](/docs/user-guide/skills/optional/data-science/data-science-jupyter-notebook) | Iterative Python via live Jupyter kernel (hamelnb). |

## devops

| Skill | Description |
|-------|-------------|
| [**actual-setup**](/docs/user-guide/skills/optional/devops/devops-actual-setup) | Set up Actual Computer (actual.inc) inference in Hermes. |
| [**docker-management**](/docs/user-guide/skills/optional/devops/devops-docker-management) | Manage Docker containers, images, volumes, and Compose. |
| [**hermes-s6-container-supervision**](/docs/user-guide/skills/optional/devops/devops-hermes-s6-container-supervision) | Modify or debug s6 services in the Hermes Docker image. |
| [**inference-sh-cli**](/docs/user-guide/skills/optional/devops/devops-inference-sh-cli) | Run 150+ AI apps (image, video, LLM) via inference.sh CLI. |
| [**pinggy-tunnel**](/docs/user-guide/skills/optional/devops/devops-pinggy-tunnel) | Zero-install localhost tunnels over SSH via Pinggy. |
| [**sdlc-review**](/docs/user-guide/skills/optional/devops/devops-sdlc-review) | Review Kanban handoffs and route verified outcomes. |
| [**watchers**](/docs/user-guide/skills/optional/devops/devops-watchers) | Poll RSS, JSON APIs, and GitHub with watermark dedup. |

## dogfood

| Skill | Description |
|-------|-------------|
| [**adversarial-ux-test**](/docs/user-guide/skills/optional/dogfood/dogfood-adversarial-ux-test) | Roleplay a hostile user to find and triage UX pain points. |
| [**dogfood**](/docs/user-guide/skills/optional/dogfood/dogfood-hermes-dogfood) | Exploratory QA of web apps: find bugs, evidence, reports. |

## email

| Skill | Description |
|-------|-------------|
| [**agentmail**](/docs/user-guide/skills/optional/email/email-agentmail) | Give the agent its own inbox: send and receive email. |
| [**email-inbox-triage**](/docs/user-guide/skills/optional/email/email-email-inbox-triage) | Triage an inbox: prioritize threads, draft replies safely. |
| [**himalaya**](/docs/user-guide/skills/optional/email/email-himalaya) | Himalaya CLI: IMAP/SMTP email from terminal. |

## finance

| Skill | Description |
|-------|-------------|
| [**3-statement-model**](/docs/user-guide/skills/optional/finance/finance-3-statement-model) | Build integrated IS/BS/CF financial workbooks in Excel. |
| [**comps-analysis**](/docs/user-guide/skills/optional/finance/finance-comps-analysis) | Build comparable-company valuation workbooks in Excel. |
| [**dcf-model**](/docs/user-guide/skills/optional/finance/finance-dcf-model) | Build discounted cash flow valuation workbooks in Excel. |
| [**excel-author**](/docs/user-guide/skills/optional/finance/finance-excel-author) | Build auditable financial workbooks headless via openpyxl. |
| [**lbo-model**](/docs/user-guide/skills/optional/finance/finance-lbo-model) | Build leveraged buyout workbooks with IRR/MOIC in Excel. |
| [**merger-model**](/docs/user-guide/skills/optional/finance/finance-merger-model) | Build M&A accretion/dilution workbooks in Excel. |
| [**polymarket**](/docs/user-guide/skills/optional/finance/finance-polymarket) | Query Polymarket: markets, prices, orderbooks, history. |
| [**pptx-author**](/docs/user-guide/skills/optional/finance/finance-pptx-author) | Build PowerPoint decks headless with python-pptx. |
| [**stocks**](/docs/user-guide/skills/optional/finance/finance-stocks) | Stock quotes, history, search, compare, crypto via Yahoo. |

## gaming

| Skill | Description |
|-------|-------------|
| [**minecraft-modpack-server**](/docs/user-guide/skills/optional/gaming/gaming-minecraft-modpack-server) | Host modded Minecraft servers (CurseForge, Modrinth). |
| [**pokemon-player**](/docs/user-guide/skills/optional/gaming/gaming-pokemon-player) | Play Pokemon via headless emulator + RAM reads. |

## github

| Skill | Description |
|-------|-------------|
| [**codebase-inspection**](/docs/user-guide/skills/optional/github/github-codebase-inspection) | Inspect codebases w/ pygount: LOC, languages, ratios. |
| [**github-auth**](/docs/user-guide/skills/optional/github/github-github-auth) | GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. |
| [**github-code-review**](/docs/user-guide/skills/optional/github/github-github-code-review) | Review PRs: diffs, inline comments via gh or REST. |
| [**github-issue-to-pr**](/docs/user-guide/skills/optional/github/github-github-issue-to-pr) | Carry a GitHub issue to a verified PR with honest CI state. |
| [**github-issues**](/docs/user-guide/skills/optional/github/github-github-issues) | Create, triage, label, assign GitHub issues via gh or REST. |
| [**github-pr-workflow**](/docs/user-guide/skills/optional/github/github-github-pr-workflow) | GitHub PR lifecycle: branch, commit, open, CI, merge. |
| [**github-repo-management**](/docs/user-guide/skills/optional/github/github-github-repo-management) | Clone/create/fork repos; manage remotes, releases. |

## health

| Skill | Description |
|-------|-------------|
| [**fitness-nutrition**](/docs/user-guide/skills/optional/health/health-fitness-nutrition) | Workout planning, macros, and body metrics via wger/USDA. |
| [**neuroskill-bci**](/docs/user-guide/skills/optional/health/health-neuroskill-bci) | Use live BCI cognitive and mood state from NeuroSkill. |

## mcp

| Skill | Description |
|-------|-------------|
| [**fastmcp**](/docs/user-guide/skills/optional/mcp/mcp-fastmcp) | Build, test, and deploy Python MCP servers. |
| [**mcp-oauth-remote-gateway**](/docs/user-guide/skills/optional/mcp/mcp-mcp-oauth-remote-gateway) | Manual OAuth for remote MCP servers on headless gateways. |
| [**mcporter**](/docs/user-guide/skills/optional/mcp/mcp-mcporter) | List, auth, and call MCP servers/tools from the terminal. |

## media

| Skill | Description |
|-------|-------------|
| [**gif-search**](/docs/user-guide/skills/optional/media/media-gif-search) | Search/download GIFs from Tenor via curl + jq. |
| [**heartmula**](/docs/user-guide/skills/optional/media/media-heartmula) | HeartMuLa: Suno-like song generation from lyrics + tags. |
| [**songsee**](/docs/user-guide/skills/optional/media/media-songsee) | Audio spectrograms/features (mel, chroma, MFCC) via CLI. |
| [**youtube-content**](/docs/user-guide/skills/optional/media/media-youtube-content) | YouTube transcripts to summaries, threads, blogs. |

## migration

| Skill | Description |
|-------|-------------|
| [**openclaw-migration**](/docs/user-guide/skills/optional/migration/migration-openclaw-migration) | Import an OpenClaw setup (memories, skills) into Hermes. |

## mlops

| Skill | Description |
|-------|-------------|
| [**accelerate**](/docs/user-guide/skills/optional/mlops/mlops-accelerate) | Run PyTorch training across GPUs with minimal changes. |
| [**audiocraft-audio-generation**](/docs/user-guide/skills/optional/mlops/mlops-models-audiocraft) | AudioCraft: MusicGen text-to-music, AudioGen text-to-sound. |
| [**axolotl**](/docs/user-guide/skills/optional/mlops/mlops-training-axolotl) | Axolotl: YAML LLM fine-tuning (LoRA, DPO, GRPO). |
| [**chroma**](/docs/user-guide/skills/optional/mlops/mlops-chroma) | Embedding database for RAG and semantic search. |
| [**clip**](/docs/user-guide/skills/optional/mlops/mlops-clip) | Zero-shot image classification and image-text search. |
| [**dspy**](/docs/user-guide/skills/optional/mlops/mlops-research-dspy) | DSPy: declarative LM programs, auto-optimize prompts, RAG. |
| [**faiss**](/docs/user-guide/skills/optional/mlops/mlops-faiss) | Fast vector similarity search at billion scale. |
| [**flash-attention**](/docs/user-guide/skills/optional/mlops/mlops-flash-attention) | Speed up long-sequence transformer training and inference. |
| [**guidance**](/docs/user-guide/skills/optional/mlops/mlops-guidance) | Constrain LLM output with grammars; guarantee valid JSON. |
| [**huggingface-hub**](/docs/user-guide/skills/optional/mlops/mlops-huggingface-hub) | HuggingFace hf CLI: search/download/upload models, datasets. |
| [**huggingface-tokenizers**](/docs/user-guide/skills/optional/mlops/mlops-huggingface-tokenizers) | Fast BPE/WordPiece tokenization and custom vocab training. |
| [**instructor**](/docs/user-guide/skills/optional/mlops/mlops-instructor) | Structured LLM outputs validated with Pydantic. |
| [**lambda-labs**](/docs/user-guide/skills/optional/mlops/mlops-lambda-labs) | On-demand GPU cloud instances for ML training. |
| [**llama-cpp**](/docs/user-guide/skills/optional/mlops/mlops-inference-llama-cpp) | llama.cpp local GGUF inference + HF Hub model discovery. |
| [**llava**](/docs/user-guide/skills/optional/mlops/mlops-llava) | Vision-language chat: VQA, captioning, image dialogue. |
| [**evaluating-llms-harness**](/docs/user-guide/skills/optional/mlops/mlops-evaluation-lm-evaluation-harness) | lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.). |
| [**modal**](/docs/user-guide/skills/optional/mlops/mlops-modal) | Serverless GPU cloud for ML jobs and model APIs. |
| [**nemo-curator**](/docs/user-guide/skills/optional/mlops/mlops-nemo-curator) | Curate LLM training data: dedupe, filter, PII redaction. |
| [**obliteratus**](/docs/user-guide/skills/optional/mlops/mlops-obliteratus) | OBLITERATUS: abliterate LLM refusals (diff-in-means). |
| [**outlines**](/docs/user-guide/skills/optional/mlops/mlops-inference-outlines) | Outlines: structured JSON/regex/Pydantic LLM generation. |
| [**peft**](/docs/user-guide/skills/optional/mlops/mlops-peft) | Fine-tune large LLMs with LoRA on limited GPU memory. |
| [**pinecone**](/docs/user-guide/skills/optional/mlops/mlops-pinecone) | Managed vector DB for production RAG and search. |
| [**pytorch-fsdp**](/docs/user-guide/skills/optional/mlops/mlops-pytorch-fsdp) | Fully sharded data-parallel training for large models. |
| [**pytorch-lightning**](/docs/user-guide/skills/optional/mlops/mlops-pytorch-lightning) | Clean training loops with built-in distributed support. |
| [**qdrant**](/docs/user-guide/skills/optional/mlops/mlops-qdrant) | Vector search engine for production RAG systems. |
| [**saelens**](/docs/user-guide/skills/optional/mlops/mlops-saelens) | Train sparse autoencoders to interpret model features. |
| [**segment-anything-model**](/docs/user-guide/skills/optional/mlops/mlops-models-segment-anything) | SAM: zero-shot image segmentation via points, boxes, masks. |
| [**segment-anything-model**](/docs/user-guide/skills/optional/mlops/mlops-models-segment-anything-model) | SAM: zero-shot image segmentation via points, boxes, masks. |
| [**simpo**](/docs/user-guide/skills/optional/mlops/mlops-simpo) | Reference-free preference alignment, simpler than DPO. |
| [**slime**](/docs/user-guide/skills/optional/mlops/mlops-slime) | RL post-training for LLMs with Megatron and SGLang. |
| [**stable-diffusion**](/docs/user-guide/skills/optional/mlops/mlops-stable-diffusion) | Text-to-image generation, inpainting, and img2img. |
| [**tensorrt-llm**](/docs/user-guide/skills/optional/mlops/mlops-tensorrt-llm) | High-throughput LLM inference on NVIDIA GPUs. |
| [**torchtitan**](/docs/user-guide/skills/optional/mlops/mlops-torchtitan) | Pretrain LLMs at scale with PyTorch 4D parallelism. |
| [**trl-fine-tuning**](/docs/user-guide/skills/optional/mlops/mlops-training-trl-fine-tuning) | TRL: SFT, DPO, GRPO, RLOO reward modeling for LLM RLHF. |
| [**unsloth**](/docs/user-guide/skills/optional/mlops/mlops-training-unsloth) | Unsloth: 2-5x faster LoRA/QLoRA fine-tuning, less VRAM. |
| [**serving-llms-vllm**](/docs/user-guide/skills/optional/mlops/mlops-inference-vllm) | vLLM: high-throughput LLM serving, OpenAI API, quantization. |
| [**weights-and-biases**](/docs/user-guide/skills/optional/mlops/mlops-evaluation-weights-and-biases) | W&B: log ML experiments, sweeps, model registry, dashboards. |
| [**whisper**](/docs/user-guide/skills/optional/mlops/mlops-whisper) | Transcribe and translate speech in 99 languages. |

## note-taking

| Skill | Description |
|-------|-------------|
| [**obsidian**](/docs/user-guide/skills/optional/note-taking/note-taking-obsidian) | Read, search, create, and edit notes in the Obsidian vault. |

## payments

| Skill | Description |
|-------|-------------|
| [**mpp-agent**](/docs/user-guide/skills/optional/payments/payments-mpp-agent) | Pay HTTP 402 APIs via Machine Payments Protocol (MPP). |
| [**stripe-link-cli**](/docs/user-guide/skills/optional/payments/payments-stripe-link-cli) | Agent payments via Stripe Link — cards, SPT, approvals. |
| [**stripe-projects**](/docs/user-guide/skills/optional/payments/payments-stripe-projects) | Provision SaaS services + sync creds via Stripe Projects. |

## productivity

| Skill | Description |
|-------|-------------|
| [**airtable**](/docs/user-guide/skills/optional/productivity/productivity-airtable) | Airtable REST API via curl. Records CRUD, filters, upserts. |
| [**box**](/docs/user-guide/skills/optional/productivity/productivity-box) | Box manages cloud files, sharing, search, and metadata. |
| [**canvas**](/docs/user-guide/skills/optional/productivity/productivity-canvas) | Fetch Canvas LMS courses and assignments via API token. |
| [**google-workspace**](/docs/user-guide/skills/optional/productivity/productivity-google-workspace) | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. |
| [**here-now**](/docs/user-guide/skills/optional/productivity/productivity-here-now) | Publish sites to &#123;slug&#125;.here.now and store files in Drives. |
| [**maps**](/docs/user-guide/skills/optional/productivity/productivity-maps) | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. |
| [**meeting-action-items**](/docs/user-guide/skills/optional/productivity/productivity-meeting-action-items) | Turn meeting notes into cited decisions, owners, tickets. |
| [**memento-flashcards**](/docs/user-guide/skills/optional/productivity/productivity-memento-flashcards) | Spaced-repetition flashcards: create, review, quiz, export. |
| [**notion**](/docs/user-guide/skills/optional/productivity/productivity-notion) | Notion API + ntn CLI: pages, databases, markdown, Workers. |
| [**petdex**](/docs/user-guide/skills/optional/productivity/productivity-petdex) | Install and select animated petdex mascots for Hermes. |
| [**product-price-monitor**](/docs/user-guide/skills/optional/productivity/productivity-product-price-monitor) | Watch product, flight, or listing prices; alert on target. |
| [**shop**](/docs/user-guide/skills/optional/productivity/productivity-shop) | Shop catalog search, checkout, order tracking, returns. |
| [**shopify**](/docs/user-guide/skills/optional/productivity/productivity-shopify) | Query Shopify Admin/Storefront GraphQL APIs via curl. |
| [**siyuan**](/docs/user-guide/skills/optional/productivity/productivity-siyuan) | Query and edit a SiYuan knowledge base via its API. |
| [**teams-meeting-pipeline**](/docs/user-guide/skills/optional/productivity/productivity-teams-meeting-pipeline) | Teams meeting summaries, job replay, Graph subscriptions. |
| [**telephony**](/docs/user-guide/skills/optional/productivity/productivity-telephony) | Provision Twilio numbers, SMS/MMS, and AI outbound calls. |
| [**weekly-review-planning**](/docs/user-guide/skills/optional/productivity/productivity-weekly-review-planning) | Weekly reset: commitments, stalled work, next-week plan. |

## research

| Skill | Description |
|-------|-------------|
| [**arxiv**](/docs/user-guide/skills/optional/research/research-arxiv) | Search arXiv papers by keyword, author, category, or ID. |
| [**bioinformatics**](/docs/user-guide/skills/optional/research/research-bioinformatics) | Gateway to 400+ genomics and computational biology skills. |
| [**blogwatcher**](/docs/user-guide/skills/optional/research/research-blogwatcher) | Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool. |
| [**darwinian-evolver**](/docs/user-guide/skills/optional/research/research-darwinian-evolver) | Evolve prompts/regex/SQL/code with Imbue's evolution loop. |
| [**domain-intel**](/docs/user-guide/skills/optional/research/research-domain-intel) | Passive recon of subdomains, SSL certs, WHOIS, and DNS. |
| [**drug-discovery**](/docs/user-guide/skills/optional/research/research-drug-discovery) | Drug discovery: ChEMBL search, drug-likeness, interactions. |
| [**duckduckgo-search**](/docs/user-guide/skills/optional/research/research-duckduckgo-search) | Free keyless web, news, and image search via ddgs. |
| [**gitnexus-explorer**](/docs/user-guide/skills/optional/research/research-gitnexus-explorer) | Serve an interactive codebase knowledge graph web UI. |
| [**llm-wiki**](/docs/user-guide/skills/optional/research/research-llm-wiki) | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| [**osint-investigation**](/docs/user-guide/skills/optional/research/research-osint-investigation) | Follow the money via public records and sanctions data. |
| [**parallel-cli**](/docs/user-guide/skills/optional/research/research-parallel-cli) | Agent-native web search, deep research, and enrichment. |
| [**pinecone-research**](/docs/user-guide/skills/optional/research/research-pinecone-research) | Agent RAG and long-term memory with Pinecone. |
| [**polymarket**](/docs/user-guide/skills/optional/research/research-polymarket) | Query Polymarket: markets, prices, orderbooks, history. |
| [**qmd**](/docs/user-guide/skills/optional/research/research-qmd) | Hybrid local search over notes, docs, and transcripts. |
| [**research-paper-writing**](/docs/user-guide/skills/optional/research/research-research-paper-writing) | Write ML papers for NeurIPS/ICML/ICLR: design→submit. |
| [**scrapling**](/docs/user-guide/skills/optional/research/research-scrapling) | Scrape sites with stealth browsing and Cloudflare bypass. |
| [**searxng-search**](/docs/user-guide/skills/optional/research/research-searxng-search) | Free keyless meta-search aggregating 70+ engines. |

## security

| Skill | Description |
|-------|-------------|
| [**1password**](/docs/user-guide/skills/optional/security/security-1password) | Set up op CLI, sign in, and read or inject secrets. |
| [**godmode**](/docs/user-guide/skills/optional/security/security-godmode) | Jailbreak LLMs: Parseltongue, GODMODE, ULTRAPLINIAN. |
| [**oss-forensics**](/docs/user-guide/skills/optional/security/security-oss-forensics) | GitHub supply-chain forensics: recovery, IOCs, reporting. |
| [**sherlock**](/docs/user-guide/skills/optional/security/security-sherlock) | Find accounts for a username across 400+ platforms. |
| [**unbroker**](/docs/user-guide/skills/optional/security/security-unbroker) | Autonomously remove your info from data-broker sites. |
| [**web-pentest**](/docs/user-guide/skills/optional/security/security-web-pentest) | Authorized web pentest: recon, proof-based exploits, report. |

## smart-home

| Skill | Description |
|-------|-------------|
| [**openhue**](/docs/user-guide/skills/optional/smart-home/smart-home-openhue) | Control Philips Hue lights, scenes, rooms via OpenHue CLI. |

## social-media

| Skill | Description |
|-------|-------------|
| [**xurl**](/docs/user-guide/skills/optional/social-media/social-media-xurl) | X/Twitter via xurl CLI: raw post search, posting, DM, media. |

## software-development

| Skill | Description |
|-------|-------------|
| [**ast-grep**](/docs/user-guide/skills/optional/software-development/software-development-ast-grep) | AST-aware structural code search and rewrite via ast-grep. |
| [**code-wiki**](/docs/user-guide/skills/optional/software-development/software-development-code-wiki) | Generate wiki docs + Mermaid diagrams for any codebase. |
| [**hermes-agent-skill-authoring**](/docs/user-guide/skills/optional/software-development/software-development-hermes-agent-skill-authoring) | Author in-repo SKILL.md files: frontmatter and structure. |
| [**inspecting-hermes-desktop-dom**](/docs/user-guide/skills/optional/software-development/software-development-inspecting-hermes-desktop-dom) | Read the live Hermes desktop DOM/CSS over CDP. |
| [**node-inspect-debugger**](/docs/user-guide/skills/optional/software-development/software-development-node-inspect-debugger) | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. |
| [**plan**](/docs/user-guide/skills/optional/software-development/software-development-plan) | Write a markdown plan to .hermes/plans/; no execution. |
| [**python-debugpy**](/docs/user-guide/skills/optional/software-development/software-development-python-debugpy) | Debug Python: pdb REPL + debugpy remote (DAP). |
| [**requesting-code-review**](/docs/user-guide/skills/optional/software-development/software-development-requesting-code-review) | Pre-commit review: security scan, quality gates, auto-fix. |
| [**rest-graphql-debug**](/docs/user-guide/skills/optional/software-development/software-development-rest-graphql-debug) | Debug REST/GraphQL APIs: status codes, auth, schemas, repro. |
| [**simplify-code**](/docs/user-guide/skills/optional/software-development/software-development-simplify-code) | Parallel 4-agent cleanup of recent code changes. |
| [**spike**](/docs/user-guide/skills/optional/software-development/software-development-spike) | Throwaway experiments to validate an idea before build. |
| [**subagent-driven-development**](/docs/user-guide/skills/optional/software-development/software-development-subagent-driven-development) | Execute plans via delegate_task subagents (2-stage review). |
| [**systematic-debugging**](/docs/user-guide/skills/optional/software-development/software-development-systematic-debugging) | 4-phase root cause debugging: understand bugs before fixing. |
| [**test-driven-development**](/docs/user-guide/skills/optional/software-development/software-development-test-driven-development) | TDD: enforce RED-GREEN-REFACTOR, tests before code. |

## web-development

| Skill | Description |
|-------|-------------|
| [**cloudflare-temporary-deploy**](/docs/user-guide/skills/optional/web-development/web-development-cloudflare-temporary-deploy) | Deploy a Worker live, no account, via wrangler --temporary. |
| [**har-derived-api-client**](/docs/user-guide/skills/optional/web-development/web-development-har-derived-api-client) | Record a site's XHR into a HAR, derive an HTTP client. |
| [**page-agent**](/docs/user-guide/skills/optional/web-development/web-development-page-agent) | Embed an in-page natural-language GUI copilot in web apps. |

## yuanbao

| Skill | Description |
|-------|-------------|
| [**yuanbao**](/docs/user-guide/skills/optional/yuanbao/yuanbao-yuanbao) | Yuanbao (元宝) groups: @mention users, query info/members. |

---

## Contributing Optional Skills

To add a new optional skill to the repository:

1. Create a directory under `optional-skills/<category>/<skill-name>/`
2. Add a `SKILL.md` with standard frontmatter (name, description, version, author)
3. Include any supporting files in `references/`, `templates/`, or `scripts/` subdirectories
4. Submit a pull request — the skill will appear in this catalog and get its own docs page once merged
