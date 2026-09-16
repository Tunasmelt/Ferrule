# Rule files

The reviewer reads every file listed in `config.rules`. Add rule files here
and register them in .agent/config.json, e.g.:

    "rules": [".agent/rules/style.md", ".agent/rules/security.md"]

Write rules as checkable statements — the reviewer must be able to cite one.
Good: "Every exported function has an explicit return type."
Bad:  "Write clean code."
