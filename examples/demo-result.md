# Demo result

Question: Where did `examples/demo/figure.svg` come from?

1. The recorded “Render demo figure” run created the SVG: `exact` task-level
   evidence.
2. `examples/demo/render.py:10` contains the statically resolved write call:
   `probable` code-to-file evidence.
3. `examples/demo/data.csv` is read by that script and appears as indirect
   upstream ancestry: `probable` static evidence.

The captured run proves the file changed during the command. The static
callsite identifies the likely writer, but remains below exact without
function-level runtime instrumentation.
