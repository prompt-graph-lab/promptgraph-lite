# PromptGraph Lite

Gallery-centered prompt and AI illustration sequence editor for Stable Diffusion / ComfyUI workflows.

PromptGraph Lite helps creators import existing AI illustration assets, review them as an image sequence, edit generation source prompts beside the images, generate candidates, insert good results back into the sequence, and save/export the project for long-term reuse.

Instead of treating prompts as one long disposable text string, PromptGraph treats each illustration and its generation source as a reusable project unit.

The goal is to make AI illustration collections:
- easier to review
- easier to clean up
- easier to reorder
- easier to branch and continue
- easier to regenerate and export safely

PromptGraph remains lineage-oriented, but Lite is now primarily image/gallery-driven. Graph and PromptCloud views still exist for understanding the whole project, while day-to-day editing starts from the gallery.

---

# Lite Gallery Workflow

PromptGraph Lite is the entry point for practical illustration-sequence editing.

The current workflow is:

1. Load an illustration set from folders, prompt text files, PNG metadata, or an existing project.
2. Review the project in Gallery Edit Mode.
3. Delete unnecessary illustrations from the active sequence.
4. Edit generation source prompts inline with each image.
5. Generate candidate images with ComfyUI, or manually add external candidate images.
6. Insert good candidates immediately after the source illustration to continue the sequence.
7. Create branch or continuation variations as alternate illustration routes.
8. Save the project and export prompt/image sets for reuse or sharing.

Lite is intentionally not a random prompt generator. It is for maintaining, modifying, and reusing existing AI illustration assets and prompt/image collections.

---

# What is PromptGraph?

Traditional prompt editing often becomes difficult as prompts grow larger.

Example:

    1girl, smile, outdoors, blue sky, detailed eyes, cinematic lighting...

As projects become larger and more repetitive:
- editing becomes difficult
- reusable structures become hard to manage
- illustration sequence order becomes unclear
- candidate outputs become hard to compare
- workflow organization becomes painful

PromptGraph organizes prompts, images, and generated candidates as a persistent project.

This enables:
- image-sequence review
- prompt source editing beside images
- candidate-based iteration
- safer project-level cleanup
- prompt structure inspection through graph and PromptCloud views
- future route/story workflow support

---

# Core Concepts

## Illustration Line

An illustration line is one item in the project sequence.

It can contain:
- a reference/original image
- generation source prompt text
- generated candidate images
- inserted continuation images
- metadata imported from generated PNG files

Example prompt:

    1girl, smile, school uniform, classroom

---

## Gallery Edit Mode

Gallery Edit Mode is the main Lite workspace.

It is designed for:
- reviewing illustrations visually
- selecting and reordering cards
- deleting unwanted items from the active sequence
- editing prompts inline
- generating or adding candidates
- inserting good candidates into the main illustration sequence

This mode is the default editing surface for Lite.

---

## Candidate Workflow

Candidates are generated or manually added images attached to an illustration line.

In Lite, a good candidate can be inserted immediately after the current illustration. This keeps the original line intact while adding the chosen result to the main sequence.

This supports practical workflows such as:
- trying several ComfyUI outputs
- choosing the best continuation
- building a story-like sequence from existing assets
- branching a set without losing the original source image

---

## Trash View Mode

Deleting an illustration in Lite removes it from the active gallery, but it does not delete the source image file from disk.

Deleted lines are marked internally with `deleted=True` and can be reviewed in Trash View Mode.

Trash View Mode lets you:
- see deleted illustrations separately from the main gallery
- restore deleted illustrations with `復帰`
- keep the main gallery focused and uncluttered

There is no permanent-delete workflow in Lite yet.

---

## Prompt Graph / PromptCloud

PromptGraph still visualizes prompt words as graph structures.

In Lite, graph and PromptCloud views are secondary, project-wide understanding tools. They help users inspect repeated words, prompt relationships, and the overall structure of an illustration collection.

Advanced graph editing and large-scale structured operations remain Pro-oriented.

---

# Current UI Direction

PromptGraph Lite currently uses Streamlit as a rapid development and validation frontend.

The current Lite build focuses on practical AI illustration production workflows:
- gallery-first review
- image sequence cleanup
- inline generation source editing
- ComfyUI single-image generation
- candidate comparison and insertion
- safe export for public sharing
- project save/load and autosave

The long-term design still separates:
- prompt operation logic
- parser logic
- graph logic
- project import/export logic
- UI/frontend layers

This enables future support for:
- APIs
- AI-agent workflows
- MCP/server integrations
- alternative frontends

---

# Features

## Available in PromptGraph Lite

- Gallery Edit Mode as the main workflow
- Inline generation source prompt editing
- Prompt-only line creation
- Candidate image generation with ComfyUI
- Manual external candidate image import
- Candidate insertion into the main illustration sequence
- Branch / continuation line creation
- Single-line reorder and multi-select sequence insertion
- Per-card deletion and selected-item deletion
- Trash View Mode for restoring deleted illustrations
- PNG metadata import for generated illustration assets
- Folder import for prompt/image collections
- Project folder creation with `project.json` and `generated/`
- JSON project save/load
- Recent project tracking
- Project autosave
- Prompt graph visualization
- PromptCloud / word frequency visualization
- Overall edit mode for project-wide structure inspection
- TXT prompt export
- Prompt/image set export with ordered prompts and available illustration images
- Public-safe export options with PNG metadata stripping
- Streamlit-based UI

Lite focuses on practical illustration-sequence editing. It supports the full basic loop of read, edit, generate, insert, save, recover, and export.

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
- AI illustration collection maintenance
- gallery-based review
- prompt editing beside images
- ComfyUI single-image iteration
- candidate insertion into an illustration sequence
- recovering deleted project items through Trash View Mode
- safe export and project persistence

Lite intentionally limits advanced global graph editing, module editing, batch generation, and experimental AI-assisted features.

The goal is:
- import existing assets
- edit the illustration sequence visually
- branch or continue selected images
- save and resume projects
- export usable prompt/image sets

---

## PromptGraph Pro

Designed for:
- fast structured editing
- larger prompt workflows
- advanced graph/prompt structure editing
- automation-oriented operations
- reusable transformation pipelines
- future AI-agent integration

Pro focuses on scalable prompt workflow editing beyond the practical gallery workflow in Lite.

---

# Why PromptGraph?

PromptGraph is not intended to be just another prompt textbox editor.

The long-term goal is:

- Prompt IDE
- AI illustration sequence editor
- Branch/route workflow system
- Scene workflow system
- AI-friendly prompt engine
- Future MCP / agent-compatible workflow platform

The project is designed around both:
- human usability
- machine-readable prompt structures

---

# Screenshots

## Prompt Graph

![Prompt Graph](docs/graph.png)

Graph and PromptCloud views help inspect repeated words and project-wide prompt relationships.

> Graph layout and visualization will continue evolving during development.

---

## Word Cloud

![Word Cloud](docs/wordcloud.png)

---

## Focus Edit Mode

![Focus Edit Mode](docs/focusedit.png)

Focus Edit remains available, but the main Lite workflow is now Gallery Edit Mode.

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

- Improve Gallery Edit Mode for larger illustration projects
- Continue validating candidate insertion workflows
- Add lightweight branch/route editing concepts
- Improve story/scene continuation workflows
- Keep graph and PromptCloud useful as project-wide understanding tools
- Separate core prompt operations from the UI
- Prompt modules in a more mature subgraph-style direction
- WD14Tagger integration
- Image-to-prompt workflows
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
