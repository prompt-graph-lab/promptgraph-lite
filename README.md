# PromptGraph Lite

PromptGraph Lite is a graph-based Prompt IDE for Stable Diffusion and AI image generation workflows.

Instead of treating prompts as a single long text string, PromptGraph visualizes prompt structure, relationships, and editing flow as a graph.

The goal is to make prompt editing:
- easier to understand
- easier to organize
- easier to reuse
- easier to evolve into scene-oriented workflows

PromptGraph is designed not only for humans, but also for future AI-assisted prompt workflows and agent-driven generation systems.

---

# What is PromptGraph?

Traditional prompt editing usually looks like this:

    1girl, smile, outdoors, blue sky, detailed eyes, cinematic lighting...

As prompts grow larger:
- editing becomes difficult
- repeated elements become hard to manage
- scene reuse becomes painful
- prompt relationships become invisible

PromptGraph approaches prompts as structured editable data.

It visualizes:
- token relationships
- prompt flow
- repeated structures
- scene composition
- edit scope

using an interactive graph UI.

---

# Core Concepts

## Prompt Line

A single generated prompt.

Example:

    1girl, smile, school uniform, classroom

---

## Focus Edit Mode

Focus Edit Mode allows editing a single prompt line safely and clearly.

In Lite edition:
- editing is intentionally restricted to focused operations
- global destructive editing is limited
- the goal is understanding and controlled editing

---

## Graph-Based Editing

PromptGraph visualizes prompt structure as nodes and edges.

This makes it easier to:
- understand repeated tokens
- inspect prompt composition
- trace scene structure
- identify reusable elements

---

## Scene-Oriented Workflow

PromptGraph is designed around prompt sequences and scene workflows rather than isolated single-image prompts.

Future workflow direction includes:
- scene management
- sequence editing
- reusable scene structures
- character/scene separation
- AI-assisted prompt generation

---

# Features

## Available in PromptGraph Lite

- Graph visualization of prompts
- Focus Edit Mode
- Prompt line editing
- Undo/history system
- Merge identical words
- Rename/Delete preview
- Keyboard shortcuts v1
- JSON save/load
- TXT export
- Streamlit-based UI
- Prompt structure inspection
- Word cloud visualization

---

## Available in PromptGraph Pro

PromptGraph Pro includes everything in Lite, plus additional advanced workflow features such as:

- Negative Prompt v1 support
- Advanced structured editing
- Expanded automation-oriented workflow features
- Future batch editing features
- Future module workflow expansion
- Future AI-assisted editing workflows

---

## Keyboard Shortcuts v1

Lite-safe shortcut support has been added.

Current shortcuts:

| Shortcut | Action |
|---|---|
| Esc | Clear graph selection |
| Ctrl/Cmd+Z | Undo |
| Ctrl/Cmd+S | Save focused line |
| Enter / F2 | Focus line editor |
| Ctrl/Cmd+C | Copy focused line prompt |

Lite edition shortcuts are intentionally focused on:
- one-line editing
- Focus Edit workflow
- safe non-destructive interaction

---

# Lite vs Pro

## PromptGraph Lite

Designed for:
- learning
- prompt understanding
- graph visualization
- safe editing
- trying the workflow

Lite intentionally restricts some global editing features.

---

## PromptGraph Pro

Designed for:
- fast structured editing
- larger workflows
- automation-oriented workflows
- advanced prompt manipulation
- future AI-agent integration

Pro includes more powerful editing capabilities and workflow features.

---

# Recent Updates

## Lite Updates

Recent Lite improvements include:

- Added keyboard shortcuts v1
- Improved Focus Edit workflow
- Improved Lite editing UX
- Improved graph editing stability
- Added Streamlit Cloud demo support
- Added local run.bat startup support

---

## Pro Updates

Recent Pro improvements include:

- Added Negative Prompt v1 support
- Improved structured editing workflow
- Expanded Prompt IDE functionality

---

# Why PromptGraph?

PromptGraph is not intended to be just another prompt textbox editor.

The long-term goal is:

- Prompt IDE
- Prompt sequence editor
- Scene generation workflow tool
- AI-friendly prompt editing system
- Future MCP / agent-compatible workflow platform

The project is being designed with both:
- human usability
- machine-readable structured workflows

in mind.

---

# 🖼️ Screenshots

## Prompt Graph

![Prompt Graph](docs/graph.png)

Merge identical words to simplify the graph and understand structure instantly.

> Graph layout will be improved in future updates.

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

```bash
pip install -r requirements.txt
streamlit run app.py
```

or use:

```txt
run.bat
```

---

# Roadmap

Planned future directions include:

- Scene structure system
- Batch editing
- Prompt modules
- AI-assisted prompt operations
- WD14Tagger integration
- Image-to-prompt workflow
- ComfyUI integration
- Sequence editing
- Prompt clustering
- Prompt relationship analysis
- AI-agent workflow support

---

# Disclaimer

PromptGraph Lite is an experimental early-stage tool.

The UI, workflow, and internal structure may change significantly during development.

Feedback and workflow experiments are welcome.

---

# License

MIT License
