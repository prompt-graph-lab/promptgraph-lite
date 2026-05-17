# PromptGraph Lite

Lineage-oriented prompt and asset editor for Stable Diffusion workflows.

PromptGraph Lite helps users import existing AI illustration assets or prompt collections, edit prompt lines as lineage/story units, and export or save the result for long-term reuse.

Instead of treating prompts as a single long text string,
PromptGraph approaches prompts as structured editable data.

The goal is to make prompts:
- easier to understand
- easier to organize
- easier to reuse
- easier to evolve into scene-oriented workflows

PromptGraph is designed not only for humans,
but also for future AI-assisted workflows and agent-driven prompt systems.

---

# Lite v1.0 Workflow

PromptGraph Lite is the entry point for the core PromptGraph concept:

1. **Import Existing Assets**: Load existing `.txt` prompt files and same-name PNG/JPG images from a directory.
2. **Prompt Lineage**: Review each prompt as a reusable line in a larger collection or story sequence.
3. **Focus Edit / Branch Story**: Safely edit one prompt line at a time and branch from existing lines to create alternate story directions.
4. **Export / Generate Result**: Generate one focused-line candidate at a time or export active prompts to combined TXT. Batch generation is Pro-only.
5. **Project Management**: Save and reload JSON projects without changing the project file format.
6. **Graph / Prompt Cloud Preview**: Inspect repeated words, relationships, and future Pro visualization potential.

Lite is intentionally not a random prompt generator. It is for maintaining, modifying, and reusing existing AI illustration assets and prompt/image collections.

---

# What is PromptGraph?

Traditional prompt editing often becomes difficult as prompts grow larger.

Example:

    1girl, smile, outdoors, blue sky, detailed eyes, cinematic lighting...

As prompts become larger and more repetitive:
- editing becomes difficult
- reusable structures become hard to manage
- scene relationships become invisible
- workflow organization becomes painful

PromptGraph visualizes prompts as graph structures.

This enables:
- prompt structure inspection
- reusable workflow thinking
- safer editing
- scene-oriented organization
- future automation-friendly workflows

---

# Core Concepts

## Prompt Token

PromptGraph internally treats prompts as structured prompt tokens rather than plain text.

This allows future support for:
- token-aware editing
- structural transformations
- AI-assisted workflows
- reusable scene operations

---

## Prompt Line

A single generated prompt.

Example:

    1girl, smile, school uniform, classroom

---

## Focus Edit Mode

Focus Edit Mode allows safe editing of a single prompt line.

Lite edition intentionally emphasizes:
- controlled editing
- understanding prompt structure
- safe local operations

Large-scale destructive editing is intentionally limited in Lite.

---

## Graph-Based Editing

PromptGraph visualizes prompts as nodes and edges.

This makes it easier to:
- understand repeated tokens
- inspect prompt composition
- identify reusable elements
- trace scene structure
- understand editing scope

---

## Scene-Oriented Workflow

PromptGraph is designed around prompt sequences rather than isolated single prompts.

Long-term workflow direction includes:
- scene management
- sequence editing
- reusable scene structures
- character/scene separation
- AI-assisted prompt generation

---

# Current UI Direction

PromptGraph currently uses Streamlit as a rapid development and validation frontend.

The current Lite build focuses on validating:
- graph-based prompt workflows
- prompt visualization
- safe editing flows
- reusable prompt operations

before moving toward heavier IDE-style frontend architecture.

The long-term design separates:
- prompt operation logic
- parser logic
- graph logic
- UI/frontend layers

This enables future support for:
- APIs
- AI-agent workflows
- MCP/server integrations
- alternative frontends

---

# Features

## Available in PromptGraph Lite

- Graph visualization of prompts
- Prompt Cloud / word frequency visualization
- Focus Edit Mode
- Prompt line editing
- Single-line branch creation from existing prompt lines
- Single-line reorder for story/lineage ordering
- Single-image ComfyUI generation from Focus Edit
- Candidate image assignment as After or Reference
- Undo/history system
- Merge identical words
- Rename/Delete preview
- JSON save/load
- TXT export
- Streamlit-based UI
- Prompt structure inspection
- Word cloud visualization
- Safe graph-oriented editing workflow

---

## Available in PromptGraph Pro

PromptGraph Pro expands the workflow with advanced structured editing and automation-oriented features.

Current and planned Pro features include:
- Negative Prompt support
- Token-aware batch editing
- Batch line editing
- Module authoring/editing
- Scene pool and advanced scene operations
- Advanced ComfyUI batch generation
- Advanced workflow operations
- Scene-oriented transformations
- Prompt normalization workflows
- AI-assisted editing systems
- Future automation / API workflows

---

# Lite vs Pro

## PromptGraph Lite

Designed for:
- learning
- prompt understanding
- graph visualization
- safe Focus Edit workflows
- trying the PromptGraph concept

Lite intentionally limits destructive global editing features.

The goal is:
- import existing assets
- understand prompt lineage
- edit one line safely
- export/regenerate through external workflows
- save and resume projects

---

## PromptGraph Pro

Designed for:
- fast structured editing
- larger prompt workflows
- automation-oriented operations
- reusable transformation pipelines
- future AI-agent integration

Pro focuses on scalable prompt workflow editing.

---

# Why PromptGraph?

PromptGraph is not intended to be just another prompt textbox editor.

The long-term goal is:

- Prompt IDE
- Prompt sequence editor
- Scene workflow system
- AI-friendly prompt engine
- Future MCP / agent-compatible workflow platform

The project is designed around both:
- human usability
- machine-readable prompt structures

---

# 🖼️ Screenshots

## Prompt Graph

![Prompt Graph](docs/graph.png)

Merge identical words to simplify graph structure and understand prompt relationships instantly.

> Graph layout and visualization will continue evolving during development.

---

## Word Cloud

![Word Cloud](docs/wordcloud.png)

---

## Focus Edit Mode

![Focus Edit Mode](docs/focusedit.png)

---

# Demo

Streamlit Cloud demo:

https://promptgraph-lite.streamlit.app/

---

# Support / FANBOX

Project page and support:

https://promptgraph.fanbox.cc/

---

# Installation

## Local Launch

    pip install -r requirements.txt
    streamlit run app.py

or:

    run.bat

---

# Roadmap

Planned future directions include:

- Continue validating PromptGraph workflows in Streamlit
- Improve graph-based editing workflows
- Separate core prompt operations from the UI
- Scene structure systems
- Sequence editing
- Prompt modules
- AI-assisted prompt operations
- WD14Tagger integration
- Image-to-prompt workflows
- ComfyUI integration
- Prompt clustering
- Prompt relationship analysis
- AI-agent workflow support
- Future frontend evolution after workflow validation

---

# Disclaimer

PromptGraph Lite is an experimental early-stage tool.

The UI, workflow, and internal structure may evolve significantly during development.

Feedback and workflow experiments are welcome.

---

# License

MIT License
