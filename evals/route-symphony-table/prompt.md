---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---

You are working in a checkout of smg-project/smg at v1.13. A maintainer asks: add tool-call parsing support for the new Acme-9B model family. Its chat template wraps each call as <acme_call>{"name": ..., "arguments": {...}}</acme_call> and the model never emits a thinking block. Do not edit files. Explain which skill and recipe you would follow and list the files you would create or change, with the verification commands.
